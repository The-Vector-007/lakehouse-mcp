"""Discovery, schema and history, straight off the Delta transaction log.

All of this comes from delta-rs reading `_delta_log/`. No Spark, no JVM: the
metadata a Delta table publishes about itself is a log of JSON commits, and reading
it is a filesystem operation.
"""

from dataclasses import dataclass
from pathlib import Path

from deltalake import DeltaTable

from lakehouse_mcp.config import Config

DELTA_LOG = "_delta_log"


@dataclass(frozen=True)
class TableRef:
    name: str
    path: str


def is_delta_table(path: Path) -> bool:
    """A Delta table is a directory with a transaction log in it. That is the whole test."""
    return (path / DELTA_LOG).is_dir()


def find_tables(config: Config, *, max_depth: int = 3) -> list[TableRef]:
    """Every Delta table under the allowlisted roots.

    Depth-limited, and it stops descending once it finds a table: the data files
    below a table are not more tables, and walking into them on a large lakehouse
    is the difference between instant and minutes.
    """
    found: list[TableRef] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(p for p in directory.iterdir() if p.is_dir())
        except PermissionError:
            return
        for entry in entries:
            if entry.name == DELTA_LOG:
                continue
            if is_delta_table(entry):
                found.append(TableRef(name=entry.name, path=str(entry)))
                continue
            walk(entry, depth + 1)

    for root in config.roots:
        if is_delta_table(root):
            found.append(TableRef(name=root.name, path=str(root)))
        else:
            walk(root, 1)
    return found


def _open(config: Config, path: str, version: int | None = None) -> DeltaTable:
    resolved = config.resolve(path)
    if not is_delta_table(resolved):
        raise FileNotFoundError(f"not a Delta table: {path}")
    return DeltaTable(str(resolved), version=version)


def type_name(field_type) -> str:
    """A plain type name, not delta-rs's repr.

    `str()` on a delta-rs primitive gives `PrimitiveType("long")`. An agent about
    to write a CAST reads that and guesses wrong. Nested types (struct, array,
    map) have no single-word name, so those fall back to the repr, which at least
    describes the shape.
    """
    inner = getattr(field_type, "type", None)
    return inner if isinstance(inner, str) else str(field_type)


def get_schema(config: Config, path: str, *, version: int | None = None) -> dict:
    """Columns, types, partitioning and the current version."""
    table = _open(config, path, version)
    schema = table.schema()
    partitions = list(table.metadata().partition_columns)

    return {
        "path": path,
        "version": table.version(),
        "partition_columns": partitions,
        "columns": [
            {
                "name": field.name,
                "type": type_name(field.type),
                "nullable": field.nullable,
                # Called out explicitly because partition columns behave differently
                # under predicate pushdown, and an agent writing a WHERE clause
                # benefits from knowing which ones are free to filter on.
                "partition": field.name in partitions,
            }
            for field in schema.fields
        ],
    }


def table_history(config: Config, path: str, *, limit: int = 20) -> list[dict]:
    """Recent commits: version, timestamp, operation, and how much it moved.

    This is the tool that answers "why did last night's load drop 12% of rows?"
    without anyone opening a notebook. The operation metrics on a Delta commit
    record the row counts, so the answer is usually visible in the log itself.
    """
    table = _open(config, path)
    commits = table.history(limit)

    return [
        {
            "version": commit.get("version"),
            "timestamp": commit.get("timestamp"),
            "operation": commit.get("operation"),
            "parameters": commit.get("operationParameters", {}),
            "metrics": commit.get("operationMetrics", {}),
            # Present when a write carried txnAppId/txnVersion, which is how the
            # producer's idempotence scheme shows up from the reader's side.
            "app_transaction": commit.get("txnId") or commit.get("engineInfo"),
        }
        for commit in commits
    ]
