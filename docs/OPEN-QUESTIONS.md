# Open questions

Where this code takes a position someone could push on.

### `pytz` is a hard dependency because of a DuckDB conversion path

DuckDB needs it to hand back timestamp-with-timezone columns. Without it a SELECT
touching a timestamp fails at fetch time with a bare `ModuleNotFoundError`, which
is a terrible error for the caller. Pinning it is the pragmatic fix; the cleaner
one is to convert through Arrow and never let DuckDB build Python datetimes.

### Metadata functions are still reachable

`SELECT * FROM duckdb_settings()` parses as a plain SELECT and is not blocked. It
leaks server configuration, not lakehouse data, and blocking it by name is
whack-a-mole. The structural fix would be an allowlist of referenced tables parsed
out of the query, which is real work.

### The row cap is a row cap, not a byte cap

`max_bytes` is configured and not yet enforced. One hundred rows of a table with a
large JSON blob per row is still enormous, and an agent's context window is the
actual constraint.

### There is no query timeout

`timeout_seconds` is configured and unused. A pathological join across large tables
holds the connection until it finishes.

### Every table is registered on every query

`run_query` opens every Delta table under the roots before executing, even if the
query touches one. Fine for six tables, wrong for six hundred. Parsing the table
references out of the SQL first would fix it and adds a SQL-parsing dependency.

### `dq_results` guesses its table by name

It looks for a table with "dq" in the name. Convention over configuration, and it
silently picks the first match if there are several.

### Is `--root` the right trust boundary?

It is coarse: any table under a root is fully readable. A real deployment would
want per-table or per-column policy, which means an identity model this does not
have.

### `job_runs` is not built

It needs a live Airflow. The tool is documented as not built rather than stubbed,
so nothing claims an ability that is not there.
