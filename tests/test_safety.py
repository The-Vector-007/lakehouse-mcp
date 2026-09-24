"""The read-only guarantee. This file is the product's warranty."""

import duckdb
import pytest

from lakehouse_mcp.safety import UnsafeQuery, assert_read_only, connect_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from t where x > 1",
        "WITH a AS (SELECT 1) SELECT * FROM a",
        "  SELECT 1;  ",
    ],
)
def test_allows_a_single_select(sql):
    assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE t",
        "DELETE FROM t",
        "UPDATE t SET x = 1",
        "INSERT INTO t VALUES (1)",
        "CREATE TABLE t AS SELECT 1",
        "ALTER TABLE t ADD COLUMN y INT",
        "COPY t TO '/tmp/leak.csv'",
        "ATTACH '/etc/passwd' AS p",
        "SET memory_limit = '1GB'",
    ],
)
def test_refuses_anything_that_is_not_a_select(sql):
    """A keyword check would let CREATE TABLE ... AS SELECT through. The parser does not."""
    with pytest.raises(UnsafeQuery):
        assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DROP TABLE t",
        "SELECT 1; SELECT 2",
        "SELECT 1; -- harmless\nDELETE FROM t",
    ],
)
def test_refuses_more_than_one_statement(sql):
    """A caller who can send two statements can send a read followed by anything."""
    with pytest.raises(UnsafeQuery):
        assert_read_only(sql)


@pytest.mark.parametrize("sql", ["", "   ", "this is not sql"])
def test_refuses_empty_and_unparseable(sql):
    with pytest.raises(UnsafeQuery):
        assert_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA database_list",
        "PRAGMA show_tables",
        "DESCRIBE SELECT 1",
        "SHOW TABLES",
        "  -- sneaky\n  PRAGMA version",
    ],
)
def test_refuses_introspection_even_though_duckdb_parses_it_as_select(sql):
    """DuckDB reports PRAGMA as a SELECT, so the type check alone would pass it.

    It cannot reach lakehouse data or the filesystem, but a tool that promises
    'read-only SELECT' should not quietly also mean 'and enumerate the server'.
    """
    with pytest.raises(UnsafeQuery):
        assert_read_only(sql)


def test_connection_cannot_reach_the_filesystem():
    """Defence in depth: even a permitted SELECT must not read local files."""
    con = connect_read_only()
    try:
        with pytest.raises(duckdb.Error):
            con.execute("SELECT * FROM read_csv('/etc/passwd')").fetchall()
    finally:
        con.close()
