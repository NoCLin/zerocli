"""zerocli: a single-file, standard-library-only CLI helper.

Only callables registered with :class:`App` or a returned :class:`Group` are
exposed. Function signatures define their command-line parameters.

The root-callback API is directly testable without changing ``sys.argv``:

>>> import contextlib
>>> import io
>>> app = App("hello")
>>> @app.main
... def greet(name: str, excited: bool = False) -> str:
...     suffix = "!" if excited else "."
...     return f"Hello, {name}{suffix}"
>>> output = io.StringIO()
>>> with contextlib.redirect_stdout(output):
...     result = app.run(["Ada", "--excited"])
>>> result
'Hello, Ada!'
>>> output.getvalue()
'Hello, Ada!\\n'
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import inspect
import json
import sys
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


@dataclass(frozen=True)
class _ParameterMetadata:
    kind: str
    default: Any = MISSING
    help: str | None = None
    metavar: str | None = None
    short: str | None = None


def Argument(*, help: str | None = None, metavar: str | None = None) -> Any:
    """Describe a positional parameter inside ``typing.Annotated``."""
    return _ParameterMetadata("argument", help=help, metavar=metavar)


def Option(
    default: Any = MISSING,
    *,
    help: str | None = None,
    metavar: str | None = None,
    short: str | None = None,
) -> Any:
    """Describe an option inside ``typing.Annotated``."""
    if short is not None and (
        len(short) != 2 or not short.startswith("-") or short.startswith("--")
    ):
        raise ValueError("an option short name must look like '-x'")
    return _ParameterMetadata(
        "option", default=default, help=help, metavar=metavar, short=short
    )


@dataclass
class _Parameter:
    name: str
    annotation: Any
    item_annotation: Any | None
    is_list: bool
    is_bool: bool
    is_option: bool
    required: bool
    default: Any
    help: str | None
    metavar: str | None
    short: str | None


@dataclass
class _Node:
    name: str
    kind: str
    parent: _Node | None = None
    help: str | None = None
    callback: Callable[..., Any] | None = None
    parameters: list[_Parameter] = field(default_factory=list)
    children: dict[str, _Node] = field(default_factory=dict)
    declaration: Callable[..., Any] | None = None

    @property
    def path(self) -> str:
        names: list[str] = []
        node: _Node | None = self
        while node is not None and node.parent is not None:
            names.append(node.name)
            node = node.parent
        return " ".join(reversed(names))


def _kebab_case(name: str) -> str:
    return name.replace("_", "-")


def _validate_name(name: str, *, what: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{what} name must not be empty")
    if name.startswith("-"):
        raise ValueError(f"{what} name must not start with '-': {name!r}")
    if any(character.isspace() for character in name):
        raise ValueError(f"{what} name must not contain whitespace: {name!r}")
    return name


def _unwrap_annotation(annotation: Any) -> tuple[Any, _ParameterMetadata | None]:
    metadata: _ParameterMetadata | None = None
    if typing.get_origin(annotation) is typing.Annotated:
        annotated_type, *extras = typing.get_args(annotation)
        relevant = [item for item in extras if isinstance(item, _ParameterMetadata)]
        if len(relevant) > 1:
            raise TypeError("a parameter may have only one Argument or Option metadata item")
        annotation = annotated_type
        metadata = relevant[0] if relevant else None

    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = typing.get_args(annotation)
        non_none = [member for member in members if member is not type(None)]
        if len(non_none) == 1 and len(non_none) != len(members):
            annotation = non_none[0]
        else:
            raise TypeError(f"unsupported union annotation: {annotation!r}")
    return annotation, metadata


def _is_enum_type(annotation: Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, enum.Enum)


def _validate_scalar(annotation: Any) -> None:
    if annotation in (str, int, float, bool, Path) or _is_enum_type(annotation):
        return
    raise TypeError(f"unsupported parameter annotation: {annotation!r}")


def _parameters_for(func: Callable[..., Any], path: str) -> list[_Parameter]:
    try:
        hints = typing.get_type_hints(func, include_extras=True)
    except Exception as error:
        raise TypeError(f"cannot resolve annotations for {path or '<root>'}: {error}") from error

    result: list[_Parameter] = []
    for raw in inspect.signature(func).parameters.values():
        if raw.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(
                f"{path or '<root>'}: parameter {raw.name!r} uses *args or **kwargs; "
                "use list[T] instead"
            )
        if raw.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise TypeError(
                f"{path or '<root>'}: positional-only parameter {raw.name!r} is unsupported"
            )

        annotation = hints.get(raw.name, str)
        annotation, metadata = _unwrap_annotation(annotation)

        is_list = typing.get_origin(annotation) is list
        item_annotation: Any | None = None
        if is_list:
            arguments = typing.get_args(annotation)
            if len(arguments) != 1 or arguments[0] not in (str, int, float, Path):
                raise TypeError(
                    f"{path or '<root>'}: unsupported list annotation for {raw.name!r}: "
                    f"{annotation!r}"
                )
            item_annotation = arguments[0]
        else:
            try:
                _validate_scalar(annotation)
            except TypeError as error:
                raise TypeError(
                    f"{path or '<root>'}: parameter {raw.name!r}: {error}"
                ) from error

        signature_default = raw.default
        metadata_default = metadata.default if metadata is not None else MISSING
        if signature_default is not inspect.Parameter.empty and metadata_default is not MISSING:
            raise TypeError(
                f"{path or '<root>'}: parameter {raw.name!r} defines a default both "
                "in its signature and in Option()"
            )
        if signature_default is not inspect.Parameter.empty:
            default = signature_default
        elif metadata_default is not MISSING:
            default = metadata_default
        else:
            default = MISSING

        forced_kind = metadata.kind if metadata is not None else None
        if raw.kind is inspect.Parameter.KEYWORD_ONLY and forced_kind == "argument":
            raise TypeError(
                f"{path or '<root>'}: keyword-only parameter {raw.name!r} cannot be an Argument"
            )
        is_option = (
            raw.kind is inspect.Parameter.KEYWORD_ONLY
            or forced_kind == "option"
            or (default is not MISSING and forced_kind != "argument")
        )
        is_bool = annotation is bool
        if is_bool and not is_option:
            raise TypeError(
                f"{path or '<root>'}: boolean parameter {raw.name!r} must be an option"
            )

        result.append(
            _Parameter(
                name=raw.name,
                annotation=annotation,
                item_annotation=item_annotation,
                is_list=is_list,
                is_bool=is_bool,
                is_option=is_option,
                required=default is MISSING,
                default=default,
                help=metadata.help if metadata is not None else None,
                metavar=metadata.metavar if metadata is not None else None,
                short=metadata.short if metadata is not None else None,
            )
        )
    return result


def _enum_converter(enum_type: type[enum.Enum]) -> Callable[[str], enum.Enum]:
    def convert(value: str) -> enum.Enum:
        for member in enum_type:
            if str(member.value) == value:
                return member
        allowed = ", ".join(str(member.value) for member in enum_type)
        raise argparse.ArgumentTypeError(f"choose from {allowed}")

    convert.__name__ = enum_type.__name__
    return convert


def _converter(annotation: Any) -> Callable[[str], Any]:
    if _is_enum_type(annotation):
        return _enum_converter(annotation)
    return annotation


def _default_metavar(annotation: Any) -> str:
    if _is_enum_type(annotation):
        return "{" + ",".join(str(item.value) for item in annotation) + "}"
    return {str: "TEXT", int: "INT", float: "FLOAT", Path: "PATH"}.get(
        annotation, "VALUE"
    )


def _add_parameter(parser: argparse.ArgumentParser, parameter: _Parameter) -> None:
    value_type = parameter.item_annotation if parameter.is_list else parameter.annotation
    assert value_type is not None
    common: dict[str, Any] = {}
    if parameter.help is not None:
        common["help"] = parameter.help

    if parameter.is_option:
        names = ["--" + _kebab_case(parameter.name)]
        if parameter.is_bool and parameter.default is True:
            names[0] = "--no-" + _kebab_case(parameter.name)
        if parameter.short is not None:
            names.insert(0, parameter.short)
        common["dest"] = parameter.name
        common["required"] = parameter.required
        if parameter.default is not MISSING:
            common["default"] = parameter.default
        if parameter.is_bool:
            common["action"] = "store_false" if parameter.default is True else "store_true"
        else:
            common["type"] = _converter(value_type)
            common["metavar"] = parameter.metavar or _default_metavar(value_type)
            if parameter.is_list:
                common["nargs"] = "+"
        parser.add_argument(*names, **common)
        return

    common["type"] = _converter(value_type)
    common["metavar"] = parameter.metavar or parameter.name
    if parameter.is_list:
        common["nargs"] = "+" if parameter.required else "*"
    elif not parameter.required:
        common["nargs"] = "?"
    if parameter.default is not MISSING:
        common["default"] = parameter.default
    parser.add_argument(parameter.name, **common)


class Group:
    """A namespace used to register nested commands and groups."""

    def __init__(self, app: App, node: _Node) -> None:
        self._app = app
        self._node = node

    def __call__(self, func: Callable[..., Any]) -> Group:
        if self._node.declaration is not None:
            raise ValueError(f"group {self._node.path!r} is already declared")
        if not self._node.name:
            self._node.name = _validate_name(_kebab_case(func.__name__), what="group")
            assert self._node.parent is not None
            self._app._add_child(self._node.parent, self._node)
        self._node.declaration = func
        if self._node.help is None:
            self._node.help = inspect.getdoc(func)
        return self

    def _require_name(self) -> None:
        if not self._node.name:
            raise ValueError("an unnamed group must first be used as a decorator")

    def command(
        self, name: str | None = None, help: str | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        self._require_name()
        return self._app._command_decorator(self._node, name, help)

    def group(self, name: str | None = None, help: str | None = None) -> Group:
        self._require_name()
        return self._app._make_group(self._node, name, help)

    def main(self, func: Callable[..., Any]) -> Callable[..., Any]:
        self._require_name()
        self._app._set_default(self._node, func)
        return func

    default = main


class App:
    """An explicitly registered command-line application."""

    def __init__(
        self,
        name: str | None = None,
        help: str | None = None,
        version: str | None = None,
    ) -> None:
        if name is not None:
            _validate_name(name, what="application")
        self.name = name
        self.help = help
        self.version = version
        self._root = _Node(name or "", "root", help=help)

    def _add_child(self, parent: _Node, child: _Node) -> None:
        if child.name in parent.children:
            path = " ".join(part for part in (parent.path, child.name) if part)
            raise ValueError(f"a command or group is already registered at {path!r}")
        parent.children[child.name] = child

    def _command_decorator(
        self, parent: _Node, name: str | None, help: str | None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        if name is not None:
            _validate_name(name, what="command")

        def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
            command_name = _validate_name(
                name if name is not None else _kebab_case(func.__name__), what="command"
            )
            node = _Node(
                command_name,
                "command",
                parent=parent,
                help=help if help is not None else inspect.getdoc(func),
                callback=func,
            )
            node.parameters = _parameters_for(func, node.path)
            self._add_child(parent, node)
            return func

        return decorate

    def command(
        self, name: str | None = None, help: str | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._command_decorator(self._root, name, help)

    def _make_group(
        self, parent: _Node, name: str | None, help: str | None
    ) -> Group:
        group_name = _validate_name(name, what="group") if name is not None else ""
        node = _Node(group_name, "group", parent=parent, help=help)
        if group_name:
            self._add_child(parent, node)
        return Group(self, node)

    def group(self, name: str | None = None, help: str | None = None) -> Group:
        return self._make_group(self._root, name, help)

    def _set_default(self, node: _Node, func: Callable[..., Any]) -> None:
        if node.callback is not None:
            location = node.path or "<root>"
            raise ValueError(f"a default callback is already registered at {location!r}")
        node.parameters = _parameters_for(func, node.path)
        node.callback = func

    def main(self, func: Callable[..., Any]) -> Callable[..., Any]:
        self._set_default(self._root, func)
        return func

    default = main

    def _select_node(self, argv: list[str]) -> tuple[_Node, list[str]]:
        node = self._root
        remaining = argv
        while node.children and remaining:
            child = node.children.get(remaining[0])
            if child is None:
                break
            node = child
            remaining = remaining[1:]
        return node, remaining

    def _prog_for(self, node: _Node) -> str | None:
        base = self.name or Path(sys.argv[0]).name
        if node.path:
            return f"{base} {node.path}"
        return base

    @staticmethod
    def _children_epilog(node: _Node) -> str | None:
        if not node.children:
            return None
        width = max(len(name) for name in node.children)
        lines = ["commands:"]
        for name, child in node.children.items():
            description = child.help or ""
            lines.append(f"  {name:<{width}}  {description}".rstrip())
        return "\n".join(lines)

    def _parser_for(self, node: _Node) -> argparse.ArgumentParser:
        description = node.help
        if description is None and node.callback is not None:
            description = inspect.getdoc(node.callback)
        parser = argparse.ArgumentParser(
            prog=self._prog_for(node),
            description=description,
            epilog=self._children_epilog(node),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        if node is self._root and self.version is not None:
            parser.add_argument("--version", action="version", version=self.version)
        if node.callback is not None:
            for parameter in node.parameters:
                _add_parameter(parser, parameter)
        elif node.children:
            parser.add_argument(
                "command",
                nargs="?",
                choices=list(node.children),
                metavar="{" + ",".join(node.children) + "}",
                help="command to run",
            )
        return parser

    def run(self, argv: Sequence[str] | None = None) -> Any:
        arguments = list(sys.argv[1:] if argv is None else argv)
        if self._root.callback is None and not self._root.children:
            raise ValueError("no command or default callback is registered")
        node, remaining = self._select_node(arguments)
        parser = self._parser_for(node)
        if node.callback is None and node.children and not remaining:
            parser.print_help()
            return None
        namespace = parser.parse_args(remaining)
        if node.callback is None:
            return None
        result = node.callback(**vars(namespace))
        _render_result(result)
        return result

    def __call__(self) -> None:
        self.run()


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _render_result(value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (dict, list, tuple)) or (
        dataclasses.is_dataclass(value) and not isinstance(value, type)
    ):
        print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))
        return
    if isinstance(value, enum.Enum):
        print(value.value)
        return
    print(value)


__all__ = ["App", "Argument", "Group", "MISSING", "Option"]
