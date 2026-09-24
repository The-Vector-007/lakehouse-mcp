"""The read-only guarantee.

This module is the product. Everything else is convenience on top of it.

The rule: a statement is allowed only if DuckDB's own parser says it is a single
SELECT. Not a keyword check, not a regex. `SELECT` appears inside
`CREATE TABLE x AS SELECT ...`, `--` comments hide trailing statements, and string
literals contain anything at all. Asking the parser is the only version of this
that does not eventually lose to a clever input.
"""

import re

import duckdb

# DuckDB parses PRAGMA as a SELECT, so the statement-type check cannot see it.
# PRAGMA cannot reach lakehouse data or the filesystem once external access is
# off, but it does enumerate server internals, and a tool that says "read-only
# SELECT" should not quietly also mean "and introspection". Matched on the
# statement text after stripping leading comments and whitespace.
_LEADING_NOISE = re.compile(r"^(?:\s|--[^\n]*\n|/\*.*?\*/)+", re.DOTALL)
_INTROSPECTION = re.compile(r"^(pragma|call|describe|show)\b", re.IGNORECASE)

# Written as strings and compared by name because DuckDB's StatementType enum has
# gained members across versions, and pinning to attributes that may not exist
# turns a dependency bump into an import error.
ALLOWED_STATEMENTS = frozenset({"SELECT"})


class UnsafeQuery(Exception):
    """A statement that is not a single read."""


def statement_kinds(sql: str) -> list[str]:
    """What DuckDB thinks this SQL is, without executing any of it."""
    try:
        statements = duckdb.extract_statements(sql)
    except Exception as exc:  # noqa: BLE001 - a parse failure is a rejection, not a crash
        raise UnsafeQuery(f"could not parse SQL: {exc}") from exc
    return [str(s.type).rsplit(".", 1)[-1].upper() for s in statements]


def assert_read_only(sql: str) -> None:
    """Raise unless `sql` is exactly one SELECT.

    Rejecting multiple statements matters as much as rejecting writes: a caller
    that can send two statements can send a read followed by anything.
    """
    if not sql or not sql.strip():
        raise UnsafeQuery("empty query")

    bare = _LEADING_NOISE.sub("", sql).lstrip()
    if _INTROSPECTION.match(bare):
        raise UnsafeQuery(f"introspection statements are not permitted: {bare.split()[0]}")

    kinds = statement_kinds(sql)
    if len(kinds) != 1:
        raise UnsafeQuery(f"expected exactly one statement, got {len(kinds)}: {kinds}")
    if kinds[0] not in ALLOWED_STATEMENTS:
        raise UnsafeQuery(f"only SELECT is permitted, got {kinds[0]}")


def connect_read_only() -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB with the filesystem escape hatches shut.

    DuckDB can read and write local files through functions like read_csv and
    COPY. The statement check already blocks COPY, but disabling external access
    means a SELECT cannot reach the filesystem either, so the only data reachable
    is what this server explicitly registered.
    """
    con = duckdb.connect(database=":memory:")
    # Order matters: the lock has to come last, because it freezes every setting
    # including the two above it.
    con.execute("SET enable_external_access = false")
    con.execute("SET disabled_filesystems = 'LocalFileSystem'")
    con.execute("SET lock_configuration = true")
    return con
