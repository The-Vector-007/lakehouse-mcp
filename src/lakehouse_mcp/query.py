"""Read-only SQL over Delta tables, executed by DuckDB.

The Delta table is handed to DuckDB as an Arrow dataset, so DuckDB never touches
the filesystem itself. Combined with `enable_external_access = false`, that means
the only data any query can reach is what this module explicitly registered.
"""

import re

from deltalake import DeltaTable

from lakehouse_mcp.config import Config
from lakehouse_mcp.safety import assert_read_only, connect_read_only
from lakehouse_mcp.tables import find_tables, is_delta_table

# DuckDB identifiers: keep registration names predictable and unquotable-surprising.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]")


def register_name(name: str) -> str:
    """A table's directory name, made safe to use as a SQL identifier."""
    cleaned = _SAFE_NAME.sub("_", name)
    return f"t_{cleaned}" if cleaned[:1].isdigit() else cleaned


def run_query(
    config: Config,
    sql: str,
    *,
    limit: int | None = None,
    table: str | None = None,
    version: int | None = None,
) -> dict:
    """Execute one SELECT against every discoverable table.

    `table` plus `version` pins that one table to a historical version, which is
    how time travel is expressed here: the same query, against yesterday's data.

    The row cap is applied by wrapping the caller's SQL rather than by trusting it
    to include a LIMIT, because a caller that forgets is exactly the case the cap
    exists for.
    """
    assert_read_only(sql)
    row_limit = config.clamp_rows(limit)

    pinned = config.resolve(table).name if table else None
    connection = connect_read_only()
    registered: dict[str, str] = {}

    try:
        for ref in find_tables(config):
            at_version = version if pinned and ref.name == pinned else None
            dataset = DeltaTable(ref.path, version=at_version).to_pyarrow_dataset()
            alias = register_name(ref.name)
            connection.register(alias, dataset)
            registered[alias] = ref.path

        # +1 so the caller can be told the result was cut rather than silently
        # handed a short answer it will reason about as if it were complete.
        wrapped = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS _q LIMIT {row_limit + 1}"
        result = connection.execute(wrapped)
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
    finally:
        connection.close()

    truncated = len(rows) > row_limit
    rows = rows[:row_limit]

    return {
        "columns": columns,
        "rows": [dict(zip(columns, row, strict=True)) for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "tables_available": sorted(registered),
        "pinned": {"table": pinned, "version": version} if pinned else None,
    }


def read_dq_results(config: Config, *, table_path: str | None = None, limit: int = 50) -> dict:
    """Latest data-quality outcomes, newest first.

    A thin wrapper over run_query, but it is the question people actually ask, and
    making an agent reconstruct the column names every time is how you get an agent
    that guesses them wrong.
    """
    candidates = [t for t in find_tables(config) if "dq" in t.name.lower()]
    if table_path:
        resolved = config.resolve(table_path)
        if not is_delta_table(resolved):
            raise FileNotFoundError(f"not a Delta table: {table_path}")
        target = register_name(resolved.name)
    elif candidates:
        target = register_name(candidates[0].name)
    else:
        raise FileNotFoundError("no data-quality table found under the configured roots")

    return run_query(
        config,
        f"SELECT * FROM {target} ORDER BY checked_at DESC, check_name",
        limit=limit,
    )
