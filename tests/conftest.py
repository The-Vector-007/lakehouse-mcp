"""Delta fixtures built with delta-rs. No Spark anywhere in this project."""

import pyarrow as pa
import pytest
from deltalake import write_deltalake

from lakehouse_mcp.config import Config


@pytest.fixture
def lakehouse(tmp_path):
    """A small lakehouse with two tables, one of which has history."""
    root = tmp_path / "warehouse"
    root.mkdir()

    transactions = pa.table(
        {
            "transaction_id": ["t1", "t2", "t3"],
            "account_id": ["a1", "a1", "a2"],
            "amount_minor": [100, 250, 700],
            "currency": ["INR", "INR", "USD"],
        }
    )
    write_deltalake(str(root / "silver"), transactions)
    # A second commit, so history and time travel have something to show.
    write_deltalake(
        str(root / "silver"),
        pa.table(
            {
                "transaction_id": ["t4"],
                "account_id": ["a3"],
                "amount_minor": [50],
                "currency": ["JPY"],
            }
        ),
        mode="append",
    )

    write_deltalake(
        str(root / "dq_results"),
        pa.table(
            {
                "check_name": ["unknown_currency", "non_positive_amount"],
                "rows_checked": [100, 100],
                "rows_failed": [2, 0],
                "checked_at": pa.array([1, 2], type=pa.int64()),
            }
        ),
    )
    return root


@pytest.fixture
def config(lakehouse):
    return Config(roots=(lakehouse.resolve(),), max_rows=10)
