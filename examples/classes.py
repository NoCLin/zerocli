"""Expose a zero-argument class as a CLI command collection.

Run from the repository root with ``python -m examples.classes``.
"""

from pathlib import Path
from typing import List

from zerocli import App


class RepositoryCommands:
    """Repository utilities organized as a command class."""

    def __init__(self) -> None:
        self.root = Path(".")

    def main(self, verbose: bool = False) -> dict:
        """Describe the configured repository without a subcommand."""
        return {"root": str(self.root), "verbose": verbose}

    def summary(self, verbose: bool = False) -> dict:
        """Describe the configured repository."""
        return {"root": str(self.root), "verbose": verbose}

    def find(self, pattern: str = "*.py", limit: int = 20) -> List[str]:
        """Find matching files below the configured repository."""
        matches = sorted(str(path) for path in self.root.rglob(pattern))
        return matches[:limit]

    def status(self, short: bool = False) -> str:
        """Show an example repository status."""
        return "clean" if short else f"working tree clean: {self.root}"

    def _normalize_path(self, path: Path) -> Path:
        """An ordinary helper; it is deliberately not registered."""
        return self.root / path


app = App(RepositoryCommands)


if __name__ == "__main__":
    app()
