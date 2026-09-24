"""Discovery, schema and history, read straight off the Delta log."""

import pytest

from lakehouse_mcp.config import AccessDenied
from lakehouse_mcp.tables import find_tables, get_schema, is_delta_table, table_history


def test_finds_every_table_under_the_roots(config):
    names = {t.name for t in find_tables(config)}
    assert names == {"silver", "dq_results"}


def test_does_not_descend_into_a_table(config, lakehouse):
    """Data files under a table are not more tables, and walking them is slow."""
    assert all(t.name != "_delta_log" for t in find_tables(config))
    assert is_delta_table(lakehouse / "silver")


def test_schema_reports_columns_and_types(config, lakehouse):
    schema = get_schema(config, str(lakehouse / "silver"))
    columns = {c["name"]: c for c in schema["columns"]}

    assert set(columns) == {"transaction_id", "account_id", "amount_minor", "currency"}
    # Delta's own type name, not delta-rs's PrimitiveType(...) repr.
    assert columns["amount_minor"]["type"] == "long"
    assert columns["currency"]["type"] == "string"
    assert schema["version"] == 1, "two commits were written, so the table is at version 1"


def test_schema_refuses_a_path_outside_the_roots(config):
    with pytest.raises(AccessDenied):
        get_schema(config, "/etc")


def test_schema_refuses_a_directory_that_is_not_a_table(config, lakehouse):
    (lakehouse / "not_a_table").mkdir()
    with pytest.raises(FileNotFoundError):
        get_schema(config, str(lakehouse / "not_a_table"))


def test_history_lists_commits_newest_first(config, lakehouse):
    history = table_history(config, str(lakehouse / "silver"))

    assert len(history) == 2
    assert {h["version"] for h in history} == {0, 1}
    assert all(h["operation"] for h in history)
    # The metrics are what let an agent answer "why did last night's load drop
    # rows?" without opening a notebook.
    assert any(h["metrics"] for h in history)


def test_history_respects_its_limit(config, lakehouse):
    assert len(table_history(config, str(lakehouse / "silver"), limit=1)) == 1
