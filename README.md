# lakehouse-mcp

**An MCP server that lets AI agents operate your lakehouse.** Point Claude (or any MCP client) at your Delta tables and it can inspect schemas, walk table history, run read-only queries, check data-quality results, and watch job runs — safely.

> ✅ **Status: all six tools work.** 57 tests pass.
> The roadmap below tracks what is actually real.

## Why

Data engineers are already using AI agents for day-to-day platform work — but agents are blind without tools. lakehouse-mcp gives them structured, **read-only-by-default** access to lakehouse state, so "why did last night's load drop 12% of rows?" becomes something an agent can actually investigate: schema → history → DQ results → offending job run.

No JVM, no Spark cluster: built on **delta-rs and DuckDB**, so it installs with pip and runs anywhere.

## Tools

| Tool | What it does |
|---|---|
| `list_tables` | Discover tables in the configured lakehouse paths |
| `get_schema` | Column names, types, partitioning for a table |
| `table_history` | Delta transaction log — versions, operations, timestamps |
| `query` | Read-only SQL via DuckDB, row-limited, time-travel aware |
| `dq_results` | Latest data-quality check outcomes per table |
| `job_runs` | Recent Airflow runs and their state, with a per-task breakdown |

## Usage

Not on PyPI yet, so run it from a clone:

```json
{
  "mcpServers": {
    "lakehouse": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/lakehouse-mcp", "lakehouse-mcp",
               "--root", "/path/to/your/warehouse"]
    }
  }
}
```

`--root` is repeatable, and nothing outside the roots you pass is reachable.

## Safety model

Read-only is the product, not a setting. Four independent controls, each tested:

1. **Only a single SELECT executes.** The check asks DuckDB's own parser, not a
   regex: `SELECT` appears inside `CREATE TABLE x AS SELECT ...`, `--` comments
   hide trailing statements, and string literals contain anything at all.
   Multi-statement input is refused outright, because a caller who can send two
   statements can send a read followed by anything.
2. **Introspection is refused too.** DuckDB parses `PRAGMA` as a SELECT, so the
   type check alone would pass it. It cannot reach your data, but a tool that
   promises read-only SELECT should not quietly also mean "and enumerate the
   server".
3. **The engine cannot touch the filesystem.** `enable_external_access=false`,
   `disabled_filesystems=LocalFileSystem`, then `lock_configuration=true` so none
   of it can be undone. Tables arrive as Arrow datasets, so the only data any
   query can reach is what the server registered.
4. **Paths are allowlisted, resolved first.** `..` and symlinks are collapsed
   before the containment check, which is the half people leave out.

Every result is row-capped, and `truncated` says so when the cap bit, so an agent
never reasons about a short answer as though it were complete.

## Roadmap

- [x] Project scaffold
- [x] P1 — `list_tables`, `get_schema`, `query` against local Delta tables
- [x] P2 — `table_history` + time-travel queries
- [x] P3 — `dq_results` + `job_runs` (Airflow REST API)
- [ ] P4 — PyPI release, demo GIF against [Streamhouse](https://github.com/The-Vector-007/streamhouse)
- [x] P5 — Hardening: statement allowlist, filesystem lockdown, row caps, path allowlist

Verified against a real lakehouse: the six Delta tables Streamhouse produces
(bronze, bronze_dlq, silver, quarantine, dq_results, gold), including time travel
and the data-quality history, plus `job_runs` against a live Airflow running
Streamhouse's daily DAG.

`job_runs` needs `AIRFLOW_API_URL` set, plus `AIRFLOW_USERNAME` and
`AIRFLOW_PASSWORD` if the API requires auth. Without it the tool says so rather
than failing obscurely.

## License

MIT
