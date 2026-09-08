# zerocli

[English](README.md) | [简体中文](README.zh-CN.md)

`zerocli` is a single-file, standard-library-only, type-hint-driven CLI helper for small Python scripts and AI-agent skills.

The complete runtime is [`zerocli.py`](zerocli.py). It supports Python 3.10+ and has no runtime or test dependencies outside the standard library. Vendor it by copying that one file next to a skill script:

```bash
cp zerocli.py path/to/skill/scripts/zerocli.py
```

Only explicitly registered functions become CLI entry points. `zerocli` does not inspect or publish unrelated module members.

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

## Nested subcommands

Groups are namespaces. Their declaration functions supply documentation but are never executed during parser construction or command dispatch.

```python
from pathlib import Path
from zerocli import App

app = App("files", help="Utilities used by a Files skill")

@app.group("repo", help="Repository operations")
def repo():
    """Manage repository files."""

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

An ordinary group invoked without a child prints its help and returns successfully. Unknown children use `argparse`'s conventional error output and exit status 2. Nesting is recursive and has no fixed depth.

The explicit form `repo = app.group("repo")` is also supported. With decorator syntax, `@app.group()` derives the group name from the declaration function.

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
| `path: Path` | required positional `PATH` |
| `count: int = 3` | `--count INT`, default `3` |
| `dry_run: bool = False` | `--dry-run` |
| `cache: bool = True` | `--no-cache` |
| `token: str` after `*` | required `--token TEXT` |
| `tags: list[str] | None = None` | `--tags VALUE [VALUE ...]` |
| `mode: Mode = Mode.safe` | enum-valued `--mode {safe,...}` |

Supported scalar annotations are `str`, `int`, `float`, `bool`, `pathlib.Path`, and `enum.Enum` subclasses. `T | None`, `Optional[T]`, and unannotated string parameters are supported. Lists may contain `str`, `int`, `float`, or `Path`.

Required parameters are positional unless keyword-only or marked with `Option`. Parameters with defaults become options unless marked with `Argument`. Long option names use kebab-case, and both `--count 3` and `--count=3` work.

Boolean options never consume a value. A `False` default creates `--flag`; a `True` default creates `--no-flag`. Omitting the option preserves the Python default exactly.

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

`Option(3)` may supply a default when the function signature has none. Defining a default both ways is rejected.

## Return values

- `None` prints nothing.
- `str`, `int`, `float`, `bool`, `Path`, enum values, and unknown objects print one line.
- `dict`, `list`, and `tuple` print readable JSON with Unicode preserved.
- Dataclass instances are converted with `dataclasses.asdict()` and printed as JSON.
- Nested paths and enums serialize to strings and enum values respectively.

Callback exceptions propagate unchanged. Parsing and conversion errors are produced by `argparse` on stderr with exit status 2.

## Testing

The suite uses only `unittest` and calls `app.run(argv)` directly:

```bash
python -m unittest discover -v
```

GitHub Actions runs the complete suite and example-command smoke tests on Python 3.10, 3.11, 3.12, 3.13, and 3.14.

## Limitations and non-goals

Version 1 deliberately rejects `*args`, `**kwargs`, positional-only parameters, complex unions, mappings as input annotations, and list element types outside the documented set. It has no async dispatch, shell completion, environment/config loading, dependency injection, colors, interactive mode, arbitrary Python literal parsing, or implicit aliases. It does not dynamically traverse objects and does not claim Fire, Typer, or Click compatibility.
