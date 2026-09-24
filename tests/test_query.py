"""Read-only SQL over the lakehouse, including the caps and time travel."""

import pytest

from lakehouse_mcp.config import AccessDenied, Config
from lakehouse_mcp.query import read_dq_results, run_query
from lakehouse_mcp.safety import UnsafeQuery


def test_queries_a_registered_table(config):
    result = run_query(config, "SELECT account_id, amount_minor FROM silver ORDER BY amount_minor")

    assert result["columns"] == ["account_id", "amount_minor"]
    assert result["row_count"] == 4
    assert result["rows"][0]["amount_minor"] == 50
    assert set(result["tables_available"]) == {"silver", "dq_results"}


def test_can_join_across_tables(config):
    """Registering everything is what makes the server useful rather than a viewer."""
    result = run_query(config, "SELECT COUNT(*) AS n FROM silver, dq_results")
    assert result["rows"][0]["n"] == 8


def test_the_arrow_dataset_still_reads_with_the_filesystem_disabled(config):
    """DuckDB has LocalFileSystem disabled; PyArrow does the file reading.

    If this ever fails, the hardening in connect_read_only() has gone too far.
    """
    assert (
        run_query(config, "SELECT SUM(amount_minor) AS total FROM silver")["rows"][0]["total"]
        == 1100
    )


def test_row_cap_applies_even_without_a_limit_clause(config):
    small = Config(roots=config.roots, max_rows=2)
    result = run_query(small, "SELECT * FROM silver")

    assert result["row_count"] == 2
    assert result["truncated"] is True, "a truncated answer must say so"


def test_not_truncated_when_everything_fits(config):
    assert run_query(config, "SELECT * FROM silver")["truncated"] is False


def test_caller_cannot_exceed_the_hard_cap(config):
    result = run_query(config, "SELECT * FROM silver", limit=10**9)
    assert result["row_count"] == 4


@pytest.mark.parametrize(
    "sql",
    ["DROP TABLE silver", "DELETE FROM silver", "CREATE TABLE x AS SELECT 1 FROM silver"],
)
def test_writes_are_refused_before_execution(config, sql):
    with pytest.raises(UnsafeQuery):
        run_query(config, sql)


def test_a_refused_write_leaves_the_table_untouched(config):
    with pytest.raises(UnsafeQuery):
        run_query(config, "DELETE FROM silver")
    assert run_query(config, "SELECT COUNT(*) AS n FROM silver")["rows"][0]["n"] == 4


def test_time_travel_pins_one_table_to_a_version(config, lakehouse):
    """The same query, against yesterday's data."""
    now = run_query(config, "SELECT COUNT(*) AS n FROM silver")
    before = run_query(
        config,
        "SELECT COUNT(*) AS n FROM silver",
        table=str(lakehouse / "silver"),
        version=0,
    )

    assert now["rows"][0]["n"] == 4
    assert before["rows"][0]["n"] == 3, "version 0 predates the append"
    assert before["pinned"] == {"table": "silver", "version": 0}


def test_time_travel_refuses_a_table_outside_the_roots(config):
    with pytest.raises(AccessDenied):
        run_query(config, "SELECT 1", table="/etc", version=0)


def test_dq_results_finds_the_table_by_itself(config):
    result = read_dq_results(config)
    checks = {r["check_name"] for r in result["rows"]}
    assert checks == {"unknown_currency", "non_positive_amount"}
