import contextlib
import dataclasses
import enum
import io
import json
import sys
import unittest
from pathlib import Path
from typing import Annotated, Optional
from unittest import mock

from zerocli import App, Argument, Option


def invoke(app, argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = app.run(argv)
    return result, stdout.getvalue(), stderr.getvalue()


def invoke_exit(app, argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        with unittest.TestCase().assertRaises(SystemExit) as caught:
            app.run(argv)
    return caught.exception.code, stdout.getvalue(), stderr.getvalue()


class RegistrationTests(unittest.TestCase):
    def test_function_names_become_kebab_case(self):
        app = App("tool")

        @app.command()
        def inspect_file():
            return "derived"

        result, _, _ = invoke(app, ["inspect-file"])
        self.assertEqual(result, "derived")

    def test_explicit_name_overrides_derived_name(self):
        app = App("tool")

        @app.command("show")
        def inspect_file():
            return "explicit"

        self.assertEqual(invoke(app, ["show"])[0], "explicit")
        self.assertEqual(invoke_exit(app, ["inspect-file"])[0], 2)

    def test_duplicate_siblings_include_path(self):
        app = App("tool")
        repo = app.group("repo")

        @repo.command("status")
        def first():
            pass

        with self.assertRaisesRegex(ValueError, "repo status"):

            @repo.command("status")
            def second():
                pass

    def test_command_group_collision_fails(self):
        app = App("tool")
        app.group("repo")
        with self.assertRaisesRegex(ValueError, "repo"):

            @app.command("repo")
            def repo_command():
                pass

    def test_duplicate_defaults_fail_at_root_and_group(self):
        app = App("tool")

        @app.main
        def first():
            pass

        with self.assertRaisesRegex(ValueError, "<root>"):
            app.default(lambda: None)

        repo = App("other").group("repo")
        repo.default(lambda: None)
        with self.assertRaisesRegex(ValueError, "repo"):
            repo.main(lambda: None)

    def test_docstrings_are_help_and_explicit_help_wins(self):
        app = App("tool")

        @app.command()
        def documented():
            """From the docstring."""

        @app.command(help="Explicit help.")
        def overridden():
            """Hidden docstring."""

        _, root_help, _ = invoke_exit(app, ["--help"])
        self.assertIn("From the docstring.", root_help)
        self.assertIn("Explicit help.", root_help)
        self.assertNotIn("Hidden docstring.", root_help)

    def test_group_decorator_does_not_execute_declaration(self):
        app = App("tool")
        calls = []

        @app.group("repo")
        def repo():
            """Repository tools."""
            calls.append("called")

        @repo.command()
        def status():
            return "clean"

        self.assertEqual(invoke(app, ["repo", "status"])[0], "clean")
        self.assertEqual(calls, [])

    def test_unnamed_group_decorator_derives_kebab_case_name(self):
        app = App("tool")

        @app.group()
        def repo_tools():
            """Repository tools."""

        repo_tools.command("status")(lambda: "clean")
        self.assertEqual(invoke(app, ["repo-tools", "status"])[0], "clean")

    def test_separate_apps_are_independent(self):
        first = App("first")
        second = App("second")
        first.command("one")(lambda: 1)
        second.command("two")(lambda: 2)
        self.assertEqual(invoke(first, ["one"])[0], 1)
        self.assertEqual(invoke(second, ["two"])[0], 2)
        self.assertEqual(invoke_exit(first, ["two"])[0], 2)

    def test_invalid_names_fail_early(self):
        app = App("tool")
        for name in ("", "-bad", "two words"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                app.group(name)
        with self.assertRaises(ValueError):
            app.command("-bad")

    def test_duplicate_group_declaration_and_unbound_unnamed_group_fail(self):
        app = App("tool")
        unnamed = app.group()
        with self.assertRaisesRegex(ValueError, "decorator"):
            unnamed.command("child")

        group = app.group("repo")
        group(lambda: None)
        with self.assertRaisesRegex(ValueError, "already declared"):
            group(lambda: None)

    def test_invalid_parameter_metadata_is_rejected(self):
        with self.assertRaises(ValueError):
            Option(short="verbose")

        def duplicate(value: Annotated[int, Option(), Argument()] = 1):
            pass

        with self.assertRaisesRegex(TypeError, "only one"):
            App("tool").main(duplicate)

        def two_defaults(value: Annotated[int, Option(2)] = 1):
            pass

        with self.assertRaisesRegex(TypeError, "both"):
            App("tool").main(two_defaults)

    def test_keyword_only_argument_and_positional_bool_are_rejected(self):
        def keyword_argument(*, value: Annotated[str, Argument()]):
            pass

        def positional_bool(value: bool):
            pass

        with self.assertRaisesRegex(TypeError, "keyword-only"):
            App("tool").main(keyword_argument)
        with self.assertRaisesRegex(TypeError, "boolean"):
            App("tool").main(positional_bool)

    def test_positional_only_and_unresolvable_annotations_are_rejected(self):
        def positional_only(value, /):
            pass

        def unresolved(value: "TypeThatDoesNotExist"):
            pass

        with self.assertRaisesRegex(TypeError, "positional-only"):
            App("tool").main(positional_only)
        with self.assertRaisesRegex(TypeError, "cannot resolve annotations"):
            App("tool").main(unresolved)


class RootCommandTests(unittest.TestCase):
    def test_empty_app_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "no command"):
            App("empty").run([])

    def test_main_runs_without_dummy_command_and_converts_values(self):
        app = App("wc")

        @app.main
        def count(path: str, limit: int = 20):
            return path, limit

        result, output, _ = invoke(app, ["README.md", "--limit", "5"])
        self.assertEqual(result, ("README.md", 5))
        self.assertEqual(json.loads(output), ["README.md", 5])

    def test_root_help_contains_callback_doc_and_parameters(self):
        app = App("wc")

        @app.main
        def count(path: str, limit: int = 20):
            """Count lines in PATH."""

        code, output, _ = invoke_exit(app, ["--help"])
        self.assertEqual(code, 0)
        self.assertEqual(output.splitlines()[0], "usage: wc [-h] [--limit INT] path")
        self.assertIn("Count lines in PATH.", output)
        self.assertIn("--limit", output)

    def test_positional_metavars_preserve_distinct_parameter_names(self):
        app = App("files")

        @app.main
        def move(source: Path, destination: Path):
            pass

        _, output, _ = invoke_exit(app, ["--help"])
        self.assertEqual(output.splitlines()[0], "usage: files [-h] source destination")
        self.assertIn("  source", output)
        self.assertIn("  destination", output)

    def test_unnamed_app_uses_process_name_in_nested_help(self):
        app = App()
        repo = app.group("repo")
        repo.command("status")(lambda: None)
        _, output, _ = invoke_exit(app, ["repo", "status", "--help"])
        self.assertIn(f"{Path(sys.argv[0]).name} repo status", output)

    def test_version(self):
        app = App("tool", version="tool 1.2.3")
        app.main(lambda: None)
        code, output, _ = invoke_exit(app, ["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(output, "tool 1.2.3\n")

    def test_repeated_runs_do_not_mutate_sys_argv(self):
        app = App("tool")

        @app.main
        def value(number: int = 1):
            return number

        before = list(sys.argv)
        self.assertEqual(invoke(app, ["--number", "2"])[0], 2)
        self.assertEqual(invoke(app, ["--number=3"])[0], 3)
        self.assertEqual(sys.argv, before)

    def test_default_alias(self):
        app = App("tool")

        @app.default
        def root():
            return "alias"

        self.assertEqual(invoke(app, [])[0], "alias")

    def test_call_uses_process_arguments(self):
        app = App("tool")
        app.main(lambda: "called")
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["tool"]), contextlib.redirect_stdout(output):
            self.assertIsNone(app())
        self.assertEqual(output.getvalue(), "called\n")


class CommandRoutingTests(unittest.TestCase):
    def test_flat_siblings_route_separately_and_appear_in_help(self):
        app = App("tool")
        app.command("add")(lambda: "add")
        app.command("remove")(lambda: "remove")
        self.assertEqual(invoke(app, ["add"])[0], "add")
        self.assertEqual(invoke(app, ["remove"])[0], "remove")
        _, help_text, _ = invoke_exit(app, ["--help"])
        self.assertIn("add", help_text)
        self.assertIn("remove", help_text)

    def test_unknown_root_command_is_argparse_error(self):
        app = App("tool")
        app.command("known")(lambda: None)
        code, _, error = invoke_exit(app, ["unknown"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", error)

    def test_command_help_lists_arguments(self):
        app = App("tool")

        @app.command()
        def copy_file(source: Path, overwrite: bool = False):
            """Copy one file."""

        _, output, _ = invoke_exit(app, ["copy-file", "--help"])
        self.assertIn("tool copy-file", output)
        self.assertIn("source", output.lower())
        self.assertIn("--overwrite", output)

    def test_nested_routes_at_arbitrary_depth(self):
        app = App("tool")
        repo = app.group("repo")
        git = repo.group("git")
        remote = git.group("remote")

        @repo.command("find")
        def find(root: Path):
            return root

        @git.command("status")
        def status(short: bool = False):
            return short

        @remote.command("add")
        def add(name: str, weight: float):
            return name, weight

        self.assertEqual(invoke(app, ["repo", "find", "."])[0], Path("."))
        self.assertTrue(invoke(app, ["repo", "git", "status", "--short"])[0])
        self.assertEqual(
            invoke(app, ["repo", "git", "remote", "add", "origin", "1.5"])[0],
            ("origin", 1.5),
        )

    def test_group_help_lists_only_direct_children_and_full_path(self):
        app = App("tool")
        repo = app.group("repo", help="Repository operations")
        git = repo.group("git", help="Git operations")
        repo.command("find")(lambda: None)
        git.command("status")(lambda: None)

        _, repo_help, _ = invoke_exit(app, ["repo", "--help"])
        self.assertIn("tool repo", repo_help)
        self.assertIn("Repository operations", repo_help)
        self.assertIn("find", repo_help)
        self.assertIn("git", repo_help)
        self.assertNotIn("status", repo_help)

        _, git_help, _ = invoke_exit(app, ["repo", "git", "--help"])
        self.assertIn("tool repo git", git_help)
        self.assertIn("status", git_help)

    def test_pure_group_without_child_prints_help_successfully(self):
        app = App("tool")
        repo = app.group("repo")
        repo.command("find")(lambda: None)
        result, output, error = invoke(app, ["repo"])
        self.assertIsNone(result)
        self.assertIn("find", output)
        self.assertEqual(error, "")

    def test_unknown_nested_child_is_argparse_error(self):
        app = App("tool")
        repo = app.group("repo")
        repo.command("find")(lambda: None)
        code, _, error = invoke_exit(app, ["repo", "missing"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", error)

    def test_group_default_and_child_coexist_with_child_precedence(self):
        app = App("tool")
        repo = app.group("repo")

        @repo.default
        def summary(name: str = "all", verbose: bool = False):
            return "summary", name, verbose

        @repo.command("find")
        def find(pattern: str = "*.py"):
            return "find", pattern

        self.assertEqual(invoke(app, ["repo"])[0], ("summary", "all", False))
        self.assertEqual(
            invoke(app, ["repo", "--verbose"])[0], ("summary", "all", True)
        )
        self.assertEqual(invoke(app, ["repo", "find"])[0], ("find", "*.py"))

    def test_root_default_and_child_coexist(self):
        app = App("tool")
        app.default(lambda: "root")
        app.command("status")(lambda: "status")
        self.assertEqual(invoke(app, [])[0], "root")
        self.assertEqual(invoke(app, ["status"])[0], "status")

    def test_child_name_wins_over_default_positional(self):
        app = App("tool")
        repo = app.group("repo")

        @repo.default
        def show(name: Annotated[str, Argument()] = "summary"):
            return "default", name

        repo.command("find")(lambda: "child")
        self.assertEqual(invoke(app, ["repo", "find"])[0], "child")
        self.assertEqual(invoke(app, ["repo", "other"])[0], ("default", "other"))


class ParameterTests(unittest.TestCase):
    def test_required_scalar_positionals_and_unannotated_input(self):
        app = App("tool")

        @app.main
        def values(text, count: int, ratio: float):
            return text, count, ratio

        self.assertEqual(invoke(app, ["hello", "4", "1.25"])[0], ("hello", 4, 1.25))

    def test_optional_scalars_defaults_equals_and_kebab_case(self):
        app = App("tool")

        @app.main
        def values(max_lines: int = 20, ratio: float = 1.0, label: str = "x"):
            return max_lines, ratio, label

        self.assertEqual(invoke(app, [])[0], (20, 1.0, "x"))
        self.assertEqual(
            invoke(app, ["--max-lines=5", "--ratio", "2.5", "--label=y"])[0],
            (5, 2.5, "y"),
        )

    def test_required_keyword_only_option(self):
        app = App("tool")

        @app.main
        def upload(*, token: str):
            return token

        self.assertEqual(invoke(app, ["--token", "secret"])[0], "secret")
        self.assertEqual(invoke_exit(app, [])[0], 2)

    def test_invalid_conversion_and_missing_value(self):
        app = App("tool")

        @app.main
        def count(value: int, limit: int = 1):
            return value + limit

        for argv in (["bad"], ["1", "--limit"]):
            with self.subTest(argv=argv):
                code, _, error = invoke_exit(app, argv)
                self.assertEqual(code, 2)
                self.assertIn("error", error)

    def test_path_and_optional_values(self):
        app = App("tool")

        @app.main
        def inspect(path: Path, limit: Optional[int] = None):
            return path, limit

        self.assertEqual(invoke(app, ["some/file"])[0], (Path("some/file"), None))
        self.assertEqual(
            invoke(app, ["some/file", "--limit", "3"])[0], (Path("some/file"), 3)
        )

    def test_enum_conversion_default_and_invalid_value(self):
        class Mode(enum.Enum):
            safe = "safe"
            fast = "fast"

        app = App("tool")

        @app.main
        def choose(mode: Mode = Mode.safe):
            return mode

        self.assertIs(invoke(app, [])[0], Mode.safe)
        self.assertIs(invoke(app, ["--mode", "fast"])[0], Mode.fast)
        code, _, error = invoke_exit(app, ["--mode", "invalid"])
        self.assertEqual(code, 2)
        self.assertIn("--mode", error)

    def test_list_convention_for_positional_and_option(self):
        positional = App("items")

        @positional.main
        def collect(values: list[int]):
            return values

        optional = App("tags")

        @optional.main
        def tags(values: list[str] | None = None):
            return values

        self.assertEqual(invoke(positional, ["1", "2", "3"])[0], [1, 2, 3])
        self.assertIsNone(invoke(optional, [])[0])
        self.assertEqual(invoke(optional, ["--values", "a", "b"])[0], ["a", "b"])

    def test_varargs_kwargs_and_complex_annotations_are_rejected(self):
        for func in (
            lambda *items: None,
            lambda **items: None,
        ):
            app = App("tool")
            with self.subTest(func=func), self.assertRaisesRegex(TypeError, "list\\[T\\]"):
                app.main(func)

        def mapping(value: dict[str, int]):
            pass

        with self.assertRaisesRegex(TypeError, "unsupported"):
            App("tool").main(mapping)

        def union(value: int | str):
            pass

        def unsupported_list(value: list[bool]):
            pass

        with self.assertRaisesRegex(TypeError, "union"):
            App("tool").main(union)
        with self.assertRaisesRegex(TypeError, "list annotation"):
            App("tool").main(unsupported_list)

    def test_annotated_argument_option_help_short_and_metavar(self):
        app = App("tool")

        @app.main
        def upload(
            path: Annotated[Path, Argument(help="File to upload", metavar="FILE")],
            retries: Annotated[int, Option(help="Retry count", short="-r")] = 3,
        ):
            return path, retries

        self.assertEqual(invoke(app, ["input.txt", "-r", "5"])[0], (Path("input.txt"), 5))
        _, output, _ = invoke_exit(app, ["--help"])
        self.assertIn("FILE", output)
        self.assertIn("File to upload", output)
        self.assertIn("-r", output)
        self.assertIn("Retry count", output)

    def test_option_metadata_can_supply_default(self):
        app = App("tool")

        @app.main
        def retry(count: Annotated[int, Option(3)]):
            return count

        self.assertEqual(invoke(app, [])[0], 3)
        self.assertEqual(invoke(app, ["--count", "7"])[0], 7)


class BooleanTests(unittest.TestCase):
    def test_false_true_and_omitted_defaults(self):
        app = App("tool")

        @app.main
        def flags(dry_run: bool = False, cache: bool = True):
            return dry_run, cache

        self.assertEqual(invoke(app, [])[0], (False, True))
        self.assertEqual(invoke(app, ["--dry-run"])[0], (True, True))
        self.assertEqual(invoke(app, ["--no-cache"])[0], (False, False))

    def test_boolean_flag_does_not_consume_positional(self):
        app = App("tool")

        @app.main
        def inspect(path: str, verbose: bool = False):
            return path, verbose

        self.assertEqual(invoke(app, ["--verbose", "README.md"])[0], ("README.md", True))


class OutputTests(unittest.TestCase):
    def app_for(self, value):
        app = App("output")
        app.main(lambda: value)
        return app

    def test_none_prints_nothing(self):
        self.assertEqual(invoke(self.app_for(None), [])[1], "")

    def test_scalars_print_one_line(self):
        for value in ("text", 42, 1.5, True, Path("a/b")):
            with self.subTest(value=value):
                self.assertEqual(invoke(self.app_for(value), [])[1], f"{value}\n")

    def test_collections_are_valid_pretty_json_and_preserve_unicode(self):
        value = {"message": "你好", "items": [1, 2]}
        output = invoke(self.app_for(value), [])[1]
        self.assertEqual(json.loads(output), value)
        self.assertIn("你好", output)
        self.assertIn("\n  ", output)
        self.assertEqual(json.loads(invoke(self.app_for(["甲", "乙"]), [])[1]), ["甲", "乙"])

    def test_dataclasses_paths_and_enums_serialize(self):
        class State(enum.Enum):
            ready = "ready"

        @dataclasses.dataclass
        class Record:
            path: Path
            state: State

        output = invoke(self.app_for(Record(Path("文件.txt"), State.ready)), [])[1]
        self.assertEqual(json.loads(output), {"path": "文件.txt", "state": "ready"})

    def test_enum_scalar_uses_value(self):
        class State(enum.Enum):
            ready = "ready"

        self.assertEqual(invoke(self.app_for(State.ready), [])[1], "ready\n")

    def test_unknown_objects_fall_back_to_str(self):
        class Custom:
            def __str__(self):
                return "custom"

        self.assertEqual(invoke(self.app_for(Custom()), [])[1], "custom\n")
        nested = json.loads(invoke(self.app_for({"value": Custom()}), [])[1])
        self.assertEqual(nested, {"value": "custom"})

    def test_callback_exceptions_propagate(self):
        app = App("tool")

        @app.main
        def fail():
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            invoke(app, [])


if __name__ == "__main__":
    unittest.main()
