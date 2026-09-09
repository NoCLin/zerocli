"""Example repository utilities suitable for an AI-agent skill script.

Run from the repository root with ``python -m examples.files``.
"""

from pathlib import Path
from typing import List

from zerocli import App


app = App("files", help="Inspect files used by a skill", version="files 1.0")


@app.command("summarize")
def summarize(path: Path, max_lines: int = 20) -> dict:
    """Summarize a UTF-8 text file."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {
        "path": str(path),
        "line_count": len(lines),
        "preview": lines[:max_lines],
    }


repo = app.group("repo", help="Repository operations")


@repo.default
def repo_summary(verbose: bool = False) -> dict:
    """Describe the repository command group."""
    return {"root": str(Path.cwd()), "verbose": verbose}


@repo.command("find")
def find_files(root: Path, pattern: str = "*.py") -> List[str]:
    """Find matching files below ROOT."""
    return [str(path) for path in root.rglob(pattern)]


git = repo.group("git", help="Git-related operations")


@git.command("status")
def status(short: bool = False) -> str:
    """Show an example repository status."""
    return "clean" if short else "working tree clean"


if __name__ == "__main__":
    app()
