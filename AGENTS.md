# CLAUDE.md — zerocli

## Mission

Build **zerocli**, a single-file, zero-third-party-dependency Python CLI framework for scripts inside AI-agent skills, especially scripts stored under directories such as `skills/<skill>/scripts/`.

The framework should remove repetitive `argparse` boilerplate while remaining predictable, explicit, easy to vendor, and easy for agents to use correctly.

The project combines:

- Fire's low-code function-to-CLI workflow.
- Typer's signature/type-hint-driven parameter declaration.
- `argparse`'s standard-library availability, help generation, validation, and conventional error behavior.

It is **not** a Fire compatibility layer and **not** a Typer compatibility layer.

## Product statement

> `zerocli` is a single-file, standard-library-only, type-hint-driven CLI helper for small Python scripts and AI-agent skills. Explicitly registered functions become safe, discoverable commands with useful help text, predictable parsing, nested command groups, optional subcommands, and testable invocation.

A consuming skill should be able to copy one file, `zerocli.py`, into its repository and write code like this:

```python
from pathlib import Path
from zerocli import App

app = App("files", help="Utilities used by the Files skill")


@app.command("summarize")
def summarize(
    path: Path,
    max_lines: int = 20,
    json_output: bool = False,
) -> dict:
    """Summarize a text file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    return {
        "path": str(path),
        "line_count": len(lines),
        "preview": lines[:max_lines],
        "json_output": json_output,
    }


@app.group("repo", help="Repository operations")
def repo() -> None:
    """Manage repository files."""


@repo.command("find")
def find_files(root: Path, pattern: str = "*.py") -> list[str]:
    """Find matching files below ROOT."""
    return [str(path) for path in root.rglob(pattern)]


@repo.group("git", help="Git-related operations")
def git() -> None:
    """Git operations."""


@git.command("status")
def status(short: bool = False) -> str:
    """Show repository status."""
    return "clean" if short else "working tree clean"


if __name__ == "__main__":
    app()
```

Expected calls:

```bash
python files.py --help
python files.py summarize README.md
python files.py summarize README.md --max-lines 5 --json-output
python files.py repo --help
python files.py repo find . --pattern '*.md'
python files.py repo git status --short
```

The framework must also support a script with **no subcommands**, where the app itself maps directly to one callable:

```python
from pathlib import Path
from zerocli import App

app = App("wc", help="Count lines in a file")


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

Expected call:

```bash
python wc.py README.md --limit 20
```

The exact spelling of the single-root callable API may be `@app.main`, `@app.default`, or another concise form, but it must be documented, stable, and tested. Prefer supporting `@app.main` as the clearest spelling and optionally aliasing `@app.default`.

## Non-negotiable constraints

- Runtime dependency policy: **Python standard library only**.
- Distribution policy: the runtime framework must be one Python file named `zerocli.py`.
- Target Python: Python 3.10+ initially.
- Do not use `click`, `typer`, `fire`, `rich`, `termcolor`, `pydantic`, `docstring_parser`, `typing_extensions`, or any external package.
- Do not shell out to external tools for parsing or help rendering.
- Do not dynamically expose every member of a module/class/object as Fire does.
- Do not require decorators for every possible use case, but decorators are the primary ergonomic API.
- Keep the public API small and explicit.
- Keep behavior deterministic and test-friendly.
- User-provided Unicode must remain supported.

## Why this exists

Skill repositories contain many small scripts. Raw `argparse` makes each script repeat parser construction, argument declarations, type conversion, boolean handling, subparser setup, dispatch, output formatting, and test setup.

zerocli should make the common case approximately as concise as a normal Python function while producing a deliberate CLI surface. It must support both:

1. A **single-command app** with no subcommands.
2. A **command tree** with one or more levels of nested subcommands.

The command tree must be explicit. Refactoring a random helper function must not silently publish it as a CLI command.

## Design principles

### Explicit exposure

Only functions explicitly registered through `@app.command()`, `@app.group()`, `@group.command()`, `@group.group()`, or the single-command decorator are externally callable.

### Signature is the contract

Use the function signature as the source of truth:

- A parameter without a default is a required positional argument unless it is keyword-only.
- A parameter with a default is an optional flag.
- `snake_case` names become `--kebab-case` options.
- Function names become kebab-case command names unless overridden.
- Type annotations determine conversion and help metavars where supported.
- A function docstring is the default command description.

### Groups are not commands unless explicitly made so

A group creates a command namespace and may have children. A group callback should not be invoked merely to construct the parser. In v1, a group can either:

- Have child commands/groups and act as a namespace, or
- Be registered with a callback that may run when the group itself is invoked, if this behavior is explicitly designed and tested.

Prefer the simpler v1 behavior: a group is a namespace and requires a child unless it has an explicit group callback/default command.

### Predictability over magical compatibility

Do not aim for Python Fire syntax compatibility. Do not accept arbitrary Python literals by default. Do not implement implicit object traversal. Avoid multiple equivalent spellings that make documentation and testing difficult.

### Testable by construction

`app.run(argv)` must be a first-class API. Tests must run commands without mutating global `sys.argv` or launching subprocesses.

### Thin standard-library foundation

Use `argparse`, `inspect`, `typing`, `pathlib`, `enum`, `json`, `dataclasses`, `sys`, and other standard-library modules as appropriate. Delegate parsing, help, and standard errors to `argparse` wherever practical.

## Required architecture

The runtime must remain one file, but its internals should have clear logical sections:

1. Public sentinels and metadata helpers.
2. Internal command/group/parameter data structures.
3. Type and annotation normalization.
4. Name conversion and command-path utilities.
5. Registration API.
6. Recursive parser construction.
7. Namespace-to-call-kwargs conversion.
8. Result rendering.
9. `App.run()` and process entrypoint behavior.

Use an internal command tree. A possible model:

```python
class _Node:
    name: str
    help: str | None
    parent: "_Node | None"
    callback: Callable[..., Any] | None
    children: dict[str, "_Node"]
    kind: Literal["root", "group", "command"]
```

The exact implementation is flexible, but nested command routing must not be implemented as ad hoc string parsing scattered throughout the module.

## Public API

Implement this minimum public API:

```python
from zerocli import App, Argument, Option
```

### App

```python
class App:
    def __init__(
        self,
        name: str | None = None,
        help: str | None = None,
        version: str | None = None,
    ) -> None: ...

    def command(
        self,
        name: str | None = None,
        help: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

    def group(
        self,
        name: str | None = None,
        help: str | None = None,
    ) -> "Group": ...

    def main(
        self,
        func: Callable[..., Any],
    ) -> Callable[..., Any]: ...

    def default(
        self,
        func: Callable[..., Any],
    ) -> Callable[..., Any]: ...

    def run(self, argv: Sequence[str] | None = None) -> Any: ...

    def __call__(self) -> None: ...
```

`@app.main` and `@app.default` may be aliases. The implementation must choose and document one canonical spelling.

### Group

A group object represents a command namespace:

```python
class Group:
    def command(
        self,
        name: str | None = None,
        help: str | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

    def group(
        self,
        name: str | None = None,
        help: str | None = None,
    ) -> "Group": ...

    def main(
        self,
        func: Callable[..., Any],
    ) -> Callable[..., Any]: ...

    def default(
        self,
        func: Callable[..., Any],
    ) -> Callable[..., Any]: ...
```

`Group` may be public or an implementation detail returned by `App.group()`, but users must be able to write naturally nested code:

```python
@app.group("repo")
def repo():
    pass

@repo.command("find")
def find(...):
    pass

@repo.group("git")
def git():
    pass

@git.command("status")
def status(...):
    pass
```

If decorator-based group callbacks create awkward semantics, an alternative explicit API is acceptable:

```python
repo = app.group("repo", help="Repository commands")

@repo.command("find")
def find(...):
    ...
```

But the final API must support nested command registration clearly and must not execute registration callbacks during parser creation.

### Metadata helpers

Optional but desirable:

```python
def Argument(
    *,
    help: str | None = None,
    metavar: str | None = None,
) -> Any: ...


def Option(
    default: Any = MISSING,
    *,
    help: str | None = None,
    metavar: str | None = None,
    short: str | None = None,
) -> Any: ...
```

Use `typing.Annotated` for metadata if it keeps the implementation clean:

```python
from typing import Annotated


def upload(
    path: Annotated[Path, Argument(help="File to upload")],
    retries: Annotated[int, Option(help="Retry count", short="-r")] = 3,
) -> None:
    ...
```

Do not make `Annotated` mandatory for normal scripts.

## Command topology requirements

### No-subcommand application

A no-subcommand app has one root callback and no command tree:

```python
app = App("wc")

@app.main
def count(path: Path, limit: int | None = None):
    ...
```

The following must work:

```bash
python wc.py FILE
python wc.py FILE --limit 10
python wc.py --help
```

Rules:

- Root arguments belong to the callback.
- `--help` describes the callback and its parameters.
- `--version` works if configured.
- No subcommand token is required.
- `app.run(argv)` invokes the callback once and returns its result.

Also support the concise alias:

```python
@app.default
def main(...):
    ...
```

if `@app.default` is chosen as an alias.

### Flat subcommands

```python
@app.command()
def add(...):
    ...

@app.command()
def remove(...):
    ...
```

Expected:

```bash
python tool.py add ...
python tool.py remove ...
```

Root help must list both commands.

### Nested subcommands

Support at least two levels:

```python
repo = app.group("repo")

@repo.command("find")
def find(...):
    ...

git = repo.group("git")

@git.command("status")
def status(...):
    ...
```

Expected:

```bash
python tool.py repo find ...
python tool.py repo git status ...
```

Support arbitrary reasonable depth through the same recursive implementation, but tests must cover at least three path components (`repo git status`). Do not create a special-case implementation for exactly two levels.

### Group help

Every group path must have help:

```bash
python tool.py repo --help
python tool.py repo git --help
```

Group help must show:

- The full or relevant command path in usage.
- The group description.
- Direct child commands/groups.
- Any group-level options if the API supports a group callback/default.

### Group invocation without a child

Choose and document one behavior:

1. If a group has children and no group callback/default, invoking it without a child prints group help and exits successfully or with a conventional usage status.
2. If a group has a callback/default, invoking it runs that callback.
3. Unknown child names produce a parser error with exit code `2`.

Prefer behavior 1 for a pure namespace and behavior 2 only when explicitly registered:

```python
repo = app.group("repo")

@repo.default
def repo_summary(...):
    ...
```

The behavior must be consistent at every nesting level.

### Groups with both a default and children

Support this topology:

```python
repo = app.group("repo")

@repo.default
def repo_summary(verbose: bool = False):
    ...

@repo.command("find")
def find(...):
    ...
```

Expected:

```bash
python tool.py repo
python tool.py repo --verbose
python tool.py repo find ...
```

When the first token after `repo` matches a child name, route to the child. Otherwise parse group-default arguments. Document the ambiguity rule if positional arguments can overlap with child names.

### Collision rules

At registration time, reject or clearly handle:

- Duplicate child names under one parent.
- A command and group with the same name under one parent.
- More than one default callback at the same node.
- Registering a root command and a root default in incompatible ways.
- Empty command names.
- Names containing whitespace or leading dashes.

Error messages should include the conflicting command path, such as `repo git status`.

## Parameter mapping

For every callable node:

| Python parameter | CLI mapping |
|---|---|
| `path: Path` | required positional `path` |
| `count: int = 3` | optional `--count INT`, default `3` |
| `dry_run: bool = False` | `--dry-run` |
| `cache: bool = True` | `--no-cache` |
| `tags: list[str] | None = None` | one documented list convention |
| `mode: Mode = Mode.safe` | enum option with allowed values |

Rules:

- Required parameters are positionals by default.
- Parameters with defaults are long options by default.
- Keyword-only parameters are options, including required keyword-only parameters.
- `snake_case` becomes `--kebab-case`.
- Support `--option value` and normal `argparse` `--option=value` syntax.
- Preserve Python defaults exactly.
- Reject bare `*args` and `**kwargs` in v1 with a clear error. Recommend `list[T]` instead.
- Do not execute callbacks while constructing parsers.

## Supported annotations in v1

Support robustly:

- `str`
- `int`
- `float`
- `bool` through flags
- `pathlib.Path`
- `enum.Enum` subclasses
- `list[str]`, `list[int]`, `list[float]`, `list[Path]`
- `T | None` and `Optional[T]`
- `typing.Annotated[T, ...]` for optional metadata
- unannotated values as `str`

For unsupported annotations, either treat them as strings or raise a clear registration-time `TypeError`; choose one policy and document it. Prefer rejecting clearly complex unsupported types rather than silently producing surprising values.

## Output behavior

Use a conservative script-friendly policy:

- `None`: print nothing.
- `str`, `int`, `float`, `bool`, `Path`: print one line.
- `dict`, `list`, `tuple`: print JSON with `ensure_ascii=False` and readable indentation.
- Dataclass instances: convert with `dataclasses.asdict()` then encode as JSON.
- Enum values: serialize `.value`.
- Unknown objects: fall back to `str(value)`.
- Do not add colors, terminal detection, rich rendering, pagers, or logging configuration in v1.

## Error behavior

- Parse errors use `argparse`: error to stderr and exit code `2`.
- User callback exceptions are not silently swallowed.
- Conversion errors identify the argument.
- Registration errors identify the full command path when possible.
- `run(argv)` must not mutate global `sys.argv`.
- `__call__()` may use process arguments and may translate an integer return value only if documented and tested.

## Non-goals for v1

Do not implement these before the core is stable:

- Fire or Typer compatibility.
- Arbitrary object attribute traversal.
- Automatic discovery of all functions in a module.
- More than one callback at a single node.
- Shell completion.
- Interactive REPL.
- Color output.
- Rich/Markdown help rendering.
- Environment variable configuration.
- Config file loading.
- Dependency injection.
- Async command execution.
- Arbitrary Python literal parsing.
- More than one kind of list syntax by default.
- Implicit aliases.

Nested commands and no-subcommand operation are **in scope**, not optional extras.

## Testing requirements

Use only `unittest` from the standard library. Do not require pytest.

Create `tests/test_zerocli.py`. Runtime consumers still only need `zerocli.py`.

Tests must call `app.run(argv)` and capture output using `contextlib.redirect_stdout`, `contextlib.redirect_stderr`, and `io.StringIO` where appropriate.

### Registration tests

- Function names become kebab-case.
- Explicit names override derived names.
- Duplicate siblings fail with `ValueError`.
- Command/group name collisions fail.
- More than one default at the same node fails.
- Docstrings become help unless overridden.
- Separate `App` instances remain independent.

### No-subcommand tests

- `@app.main` runs a root callable with positional arguments.
- Root options work.
- Root `--help` shows callback documentation and parameters.
- Root `--version` works.
- A no-subcommand app does not require a dummy command token.
- Repeated `app.run([...])` calls work.
- `@app.default` alias works if provided.

### Flat command tests

- Two sibling commands route to separate functions.
- Root help lists sibling commands.
- Unknown command fails with exit code `2`.
- Command-level help lists its arguments.

### Nested command tests

- `repo find` routes correctly.
- `repo git status` routes correctly.
- Nested path parameters convert correctly.
- `repo --help` lists direct children.
- `repo git --help` lists `status`.
- Unknown nested child fails with exit code `2`.
- A nested group with no child follows the documented behavior.
- A group default and group child coexist correctly.
- Child names take precedence over a group default when the first token matches a child.
- Three or more levels use the same recursive path-building logic.

### Parameter tests

- Required string/int/float positionals.
- Optional scalar flags and defaults.
- Both `--option value` and `--option=value`.
- Kebab-case mapping.
- Required keyword-only option.
- Unannotated string input.
- Invalid conversion and missing values return parser failure code `2`.
- `Path` conversion.
- Enum conversion and invalid enum values.
- Optional values.
- The selected list convention.
- `*args`/`**kwargs` rejection.

### Boolean tests

- `False` default produces `--flag`.
- `True` default produces `--no-flag`.
- Omitted booleans retain defaults.
- Boolean flags do not consume a following positional token.

### Output tests

- `None` prints nothing.
- Scalar prints one line.
- Dictionaries/lists are valid JSON.
- Non-ASCII output is preserved.
- Dataclasses and enums serialize as documented.
- Unknown objects fall back to `str()`.

## Documentation requirements

Maintain both `README.md` (English) and `README.zh-CN.md` (Simplified Chinese).
The two files must link to each other near the top and must remain synchronized
when behavior, examples, supported versions, testing, or limitations change.

Both READMEs must cover:

- One-sentence purpose.
- Single-file and zero-dependency guarantee.
- Copy/vendor installation instructions.
- Supported Python version.
- No-subcommand quick start.
- Flat subcommand quick start.
- Nested subcommand quick start.
- Group help behavior.
- Group defaults if implemented.
- Parameter mapping table.
- Boolean behavior.
- List argument syntax.
- Return-value output behavior.
- Testing command:

  ```bash
  python -m unittest discover -v
  ```

- Explicit non-goals and limitations.

Use examples relevant to skill scripts: file inspection, JSON transformation, repository utilities, or structured output. Include at least one example with a nested command path.

## Type and compatibility discipline

`zerocli` is itself a typed library, not only a library that consumes user type
annotations. Treat its annotations and generated CLI type behavior as stable,
reviewable contracts.

- Add annotations to public APIs and internal helpers. Avoid unbounded `Any`
  where a useful concrete type can be stated without making the single-file
  implementation harder to understand.
- On Python 3.10+, import runtime collection protocols such as `Callable` and
  `Sequence` from `collections.abc`. Use `typing` for facilities such as `Any`,
  `Annotated`, `get_args`, `get_origin`, and `get_type_hints`.
- Keep all syntax and standard-library usage compatible with Python 3.10. A
  change that passes only on the developer's newest Python is not acceptable.
- Keep the distinction between the framework's own annotations and supported
  user callback annotations explicit. Extending either surface requires tests.
- Unsupported callback annotations must fail at registration time with a clear
  `TypeError`; they must not silently degrade into surprising string parsing.
- Default positional metavars use the Python parameter name so multiple values
  of the same type remain distinguishable (`source destination`, not
  `PATH PATH`). Options may use type-oriented metavars such as `INT` and `PATH`.
  Explicit `Argument(metavar=...)` and `Option(metavar=...)` metadata override
  those defaults.
- Tests for help output must assert the relevant usage line or argument section
  precisely. Do not use a substring assertion that can accidentally match a
  docstring or unrelated help text.

Do not add a mandatory external type checker: the repository must retain its
zero-third-party-dependency test policy. Type-focused behavior is enforced with
`unittest`, Python 3.10-compatible syntax checks, and the CI version matrix.

## Project maintenance foundations

- Keep `.github/workflows/ci.yml` running the full standard-library test suite
  on Python 3.10, 3.11, 3.12, 3.13, and 3.14 for pushes and pull requests.
- CI must also smoke-test the documented example command paths. Updating an
  example requires updating its smoke test when the invocation changes.
- Keep at least one executable public-API doctest in `zerocli.py`. It must be
  integrated into `python -m unittest discover -v`, and the suite must contain
  a guard that fails if all doctest examples are accidentally removed.
- Keep realistic scripts under `examples/`; examples are part of the supported
  documentation surface and must use only the public API.
- Never commit generated `__pycache__`, `.pyc`, coverage, or temporary files.
- Before reporting completion, run the complete unit/doctest suite, the example
  smoke commands, a Python 3.10 syntax compatibility check, and
  `git diff --check`.
- When asked to commit in this repository, use repository-local identity
  `Anonymous <anonymous@localhost>`. Never change the user's global Git identity.

## Acceptance criteria

The project is ready when:

1. `zerocli.py` is the only runtime file required by a consuming skill.
2. It imports in a clean Python 3.10+ environment with no third-party packages.
3. A no-subcommand script can be expressed with one decorated typed function and no direct `argparse` calls.
4. A flat command app can register multiple commands with no direct parser setup.
5. A nested command tree can reach at least `repo git status`.
6. Root, group, and leaf help work.
7. Type conversion, defaults, booleans, paths, lists, output, and errors behave as documented.
8. `app.run(argv)` is deterministic and testable.
9. Tests run with:

   ```bash
   python -m unittest discover -v
   ```

10. Documentation does not claim Fire/Typer compatibility.
11. The implementation contains no external runtime or test dependency.
12. English and Simplified Chinese READMEs are synchronized and mutually linked.
13. The public doctest is non-empty and runs through unittest discovery.
14. CI tests every supported Python minor version from 3.10 through 3.14 and
    smoke-tests the examples.

## Recommended development order

Implement in verified increments:

1. Define the internal recursive node tree and registration collision rules.
2. Implement a no-subcommand root callback with scalar arguments.
3. Implement flat `@app.command()` registration and dispatch.
4. Implement recursive `Group` registration and nested parser construction.
5. Implement root/group/leaf help and no-child group behavior.
6. Implement group defaults only after ordinary groups and nested commands work.
7. Add optional flags and kebab-case mapping.
8. Add booleans.
9. Add output rendering.
10. Add `Path`, `Enum`, optional values, and one list convention.
11. Add metadata helpers/`Annotated` only if they improve examples without bloating the core.
12. Add documentation and a realistic skill example.

At every step, add tests before broadening scope.

## Agent instructions

- Begin by proposing the repository layout and an implementation plan tied to the acceptance criteria.
- Implement a minimal vertical slice first and run tests immediately.
- Do not add external dependencies, including test-only dependencies.
- Follow the type, compatibility, documentation, doctest, example, and CI
  foundations above for every change, not only for release work.
- Prefer behavior inferable from a function signature.
- Keep nested routing recursive and data-driven; do not special-case particular command names or depths.
- Do not execute callbacks when building parsers.
- Keep the public API and CLI output stable.
- If a feature threatens the single-file/zero-dependency promise, propose an opt-in design instead of silently adding it.
- Do not copy code or tests wholesale from Fire, Typer, Click, or other projects. Implement independently and respect licenses.
- When reporting completion, include changed files, supported command topologies, known limitations, and the exact test command/results.

## Final deliverables

- `zerocli.py`: complete single-file runtime library.
- `tests/test_zerocli.py`: standard-library `unittest` coverage.
- `tests/test_doctest.py`: doctest integration and non-empty-example guard.
- `README.md` and `README.zh-CN.md`: synchronized usage and limitations.
- `examples/files.py` or equivalent: realistic no-subcommand and/or nested-command skill example.
- `.github/workflows/ci.yml`: Python 3.10-3.14 unit and smoke-test matrix.
- A short final implementation note with API decisions, nested command behavior, group-default behavior, list syntax, limitations, and test results.
