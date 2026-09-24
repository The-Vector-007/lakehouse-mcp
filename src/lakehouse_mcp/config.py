"""Where the server is allowed to look, and how much it will hand back.

Every limit here exists because an agent is the caller. An agent will happily ask
for a billion rows, follow a path out of the lakehouse, and retry a query that
already timed out, none of it maliciously. The server has to be the adult.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# An agent asking an open question ("what is in this table?") should get something
# it can reason about, not something that fills its context window.
DEFAULT_MAX_ROWS = 100
HARD_MAX_ROWS = 10_000

# Belt and braces alongside the row cap: 100 rows of a table with a wide JSON blob
# per row is still enormous.
DEFAULT_MAX_BYTES = 1_000_000

# A runaway scan should fail rather than hold the connection open.
DEFAULT_TIMEOUT_SECONDS = 30


class AccessDenied(Exception):
    """A request pointed outside the allowlisted roots."""


@dataclass(frozen=True)
class Config:
    roots: tuple[Path, ...] = field(default_factory=tuple)
    max_rows: int = DEFAULT_MAX_ROWS
    max_bytes: int = DEFAULT_MAX_BYTES
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, roots: list[str] | None = None) -> "Config":
        raw = roots or [r for r in os.getenv("LAKEHOUSE_ROOTS", "").split(os.pathsep) if r]
        return cls(
            roots=tuple(Path(r).expanduser().resolve() for r in raw),
            max_rows=int(os.getenv("LAKEHOUSE_MAX_ROWS", DEFAULT_MAX_ROWS)),
            max_bytes=int(os.getenv("LAKEHOUSE_MAX_BYTES", DEFAULT_MAX_BYTES)),
            timeout_seconds=int(os.getenv("LAKEHOUSE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        )

    def resolve(self, candidate: str | Path) -> Path:
        """Resolve a path and prove it is inside an allowlisted root.

        `resolve()` before the check, not after: it collapses `..` and follows
        symlinks, so a path that *looks* contained cannot escape through either.
        Checking the string first and resolving later is the classic traversal bug.
        """
        if not self.roots:
            raise AccessDenied("no lakehouse roots configured; start the server with --root")

        target = Path(candidate).expanduser().resolve()
        for root in self.roots:
            if target == root or root in target.parents:
                return target
        raise AccessDenied(f"path is outside the allowlisted roots: {candidate}")

    def clamp_rows(self, requested: int | None) -> int:
        """Never hand back more than HARD_MAX_ROWS, whatever the caller asks for."""
        if requested is None:
            return self.max_rows
        return max(1, min(int(requested), HARD_MAX_ROWS))
