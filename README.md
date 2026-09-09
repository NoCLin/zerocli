# zerocli

[English](README.md) | [简体中文](README.zh-CN.md)

`zerocli` is a single-file, standard-library-only, type-hint-driven CLI helper for small Python scripts and AI-agent skills.

The complete runtime is [`zerocli.py`](zerocli.py). It supports Python 3.10+ and has no runtime or test dependencies outside the standard library. Vendor it by copying that one file next to a skill script:

```bash
cp zerocli.py path/to/skill/scripts/zerocli.py
```

Only explicitly registered functions become CLI entry points, except for the controlled `App(CommandClass)` mode documented below. `zerocli` does not inspect modules, arbitrary objects, or command return values.

## A script with no subcommands

`@app.main` is the canonical root-callback spelling. `@app.default` is an exact alias.

```python
from pathlib import Path
from zerocli import App

app = App("wc", help="Count lines in a file", version="wc 1.0")

@app.main
def count_lines(path: Path, limit: int | None = None) -> dict:
    """Count lines in PATH."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[:limit]
    return {"path": str(path), "lines": len(lines)}

if __name__ == "__main__":
    app()
```

```bash
python wc.py README.md --limit 20
python wc.py --help
python wc.py --version
```

`app.run(argv)` invokes the same parser without changing `sys.argv`, returns the callback result, and is the preferred test API.

## Flat subcommands

```python
from zerocli import App

app = App("json-tool")

@app.command()
def compact(text: str) -> dict:
    """Parse JSON text."""
    import json
    return json.loads(text)

@app.command("validate")
def check(text: str) -> bool:
    """Report whether JSON text is valid."""
    import json
    json.loads(text)
    return True
```

Function names are converted from `snake_case` to `kebab-case`; an explicit decorator name overrides the derived name.

## Organizing commands with a class

Pass a zero-argument class directly to `App` to expose its public methods as flat commands:

```python
from zerocli import App

class Calculator:
    """A calculator command collection."""

    def __init__(self) -> None:
        self.offset = 1

    def main(self, value: int = 0) -> int:
        """Run without a subcommand."""
        return value + self.offset

    def add(self, left: int, right: int) -> int:
        """Add two integers and the configured offset."""
        return left + right + self.offset

    def _audit(self) -> None:
        pass  # Private methods are not exposed.

app = App(Calculator)

if __name__ == "__main__":
    app()
```

```bash
python calculator.py
python calculator.py --value 4
python calculator.py add 10 20
```

`main` is the class-mode root callback: a class with only `main` is a no-subcommand app, while `main` may also coexist with other method commands. An exact child name wins over `main` arguments, using the same rule as ordinary root defaults.

`App(CommandClass)` exposes only public instance methods declared directly in that class. It excludes static methods, class methods, private methods, inherited methods, properties, data attributes, and members of returned objects. snake_case method names become kebab-case commands.

The constructor must accept no arguments. A fresh instance is created for every `app.run(...)` call after parsing succeeds; registration and help never instantiate the class. The application name defaults to the class name, the class docstring describes root help, and method docstrings describe commands. See the runnable [`examples/classes.py`](examples/classes.py).

## Nested subcommands

Groups are explicit namespaces created with `app.group(name)` or `group.group(name)`. Put executable group behavior and parameters in an explicit `@group.default` callback.

```python
from pathlib import Path
from zerocli import App

app = App("files", help="Utilities used by a Files skill")

repo = app.group("repo", help="Repository operations")

@repo.command("find")
def find_files(root: Path, pattern: str = "*.py") -> list[str]:
    """Find matching files below ROOT."""
    return [str(path) for path in root.rglob(pattern)]

git = repo.group("git", help="Git-related operations")

@git.command("status")
def status(short: bool = False) -> str:
    """Show repository status."""
    return "clean" if short else "working tree clean"

if __name__ == "__main__":
    app()
```

```bash
python files.py repo --help
python files.py repo find . --pattern '*.md'
python files.py repo git --help
python files.py repo git status --short
```

Any group without a default invoked without a child prints its help and returns successfully, including an empty group. Unknown children use `argparse`'s conventional error output and exit status 2. A child must be written directly after its parent: placing `--` before a child is rejected rather than silently bypassing dispatch. Nesting is data-driven and has no fixed depth.

### Group defaults

A group may explicitly handle invocation without a child:

```python
repo = app.group("repo")

@repo.default
def repo_summary(verbose: bool = False) -> dict:
    return {"summary": True, "verbose": verbose}

@repo.command("find")
def find(pattern: str = "*.py") -> list[str]:
    return [pattern]
```

`files repo` and `files repo --verbose` invoke the default; `files repo find` invokes the child. Routing examines the first token after a group: an exact child name always wins, otherwise all remaining tokens are parsed as default arguments. Consequently, a default positional value identical to a child name cannot be passed in that position. Root defaults and root children follow the same rule.

## Parameter mapping

| Python signature | CLI form |
|---|---|
| `path: Path` | required positional `path` |
| `count: int = 3` | `--count INT`, default `3` |
| `dry_run: bool = False` | `--dry-run` |
| `cache: bool = True` | `--no-cache` |
| `token: str` after `*` | required `--token TEXT` |
| `tags: list[str] | None = None` | `--tags TEXT [TEXT ...]` |
| `mode: Mode = Mode.safe` | enum-valued `--mode {safe,...}` |

Supported scalar annotations are `str`, `int`, `float`, `bool`, `pathlib.Path`, and `enum.Enum` subclasses. `T | None`, `Optional[T]`, and unannotated string parameters are supported. Lists may contain `str`, `int`, `float`, or `Path`.

Required parameters are positional unless keyword-only or marked with `Option`. Parameters with defaults become options unless marked with `Argument`. Long option names use kebab-case, and both `--count 3` and `--count=3` work.

Long option names must be spelled exactly; prefix abbreviations such as `--max-l` for `--max-lines` are rejected. Generated long names, short names, built-in help flags, and the configured root `--version` flag are checked for collisions at registration time. Short options consist of `-` plus one non-whitespace Unicode character; `-h` is reserved for help.

Boolean options never consume a value. A `False` default creates `--flag`; a `True` default creates `--no-flag`. Omitting the option preserves the Python default exactly. A boolean parameter must have a default because a required flag cannot represent both boolean values; required booleans are rejected during registration.

Lists use one syntax: consecutive values after one option, such as `--tags docs urgent`, or consecutive positional values. An optional list occurrence requires at least one value. Place list options after required positionals when their boundary would otherwise be ambiguous.

### Parameter documentation

`typing.Annotated` metadata is optional:

```python
from typing import Annotated
from pathlib import Path
from zerocli import Argument, Option

def upload(
    path: Annotated[Path, Argument(help="File to upload", metavar="FILE")],
    retries: Annotated[int, Option(help="Retry count", short="-r")] = 3,
):
    ...
```

Defaults always come from the Python function signature; `Option` only supplies CLI metadata.

## Return values

- `None` prints nothing.
- `str`, `int`, `float`, `bool`, `Path`, enum values, and unknown objects print one line.
- `dict`, `list`, and `tuple` print readable JSON with Unicode preserved.
- Dataclass instances are converted with `dataclasses.asdict()` and printed as JSON.
- Nested paths, enums, and unknown values are normalized recursively.
- Structured output is strict JSON; non-finite floats such as NaN and Infinity raise `ValueError` rather than emitting non-standard tokens.
- Mapping keys follow `json.dumps` rules and must be `str`, `int`, `float`, `bool`, or `None`.

Callback exceptions propagate unchanged. Parsing and conversion errors are produced by `argparse` on stderr with exit status 2.

## Testing

The suite uses only `unittest`, calls `app.run(argv)` directly, and includes a
doctest for the public root-callback example:

```bash
python -m unittest discover -v
```

GitHub Actions runs the complete suite and example-command smoke tests on Python 3.10, 3.11, 3.12, 3.13, and 3.14.

## Limitations and non-goals

Version 1 deliberately rejects `*args`, `**kwargs`, positional-only parameters, complex unions, mappings as input annotations, and list element types outside the documented set. Command decorators require parentheses, including `@app.command()`. Groups use only the explicit `app.group(name)` form. It has no async dispatch, shell completion, environment/config loading, dependency injection, colors, interactive mode, arbitrary Python literal parsing, or implicit aliases. It does not dynamically traverse objects and does not claim Fire, Typer, or Click compatibility.
