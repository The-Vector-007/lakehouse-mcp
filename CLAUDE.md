# CLAUDE.md

## What this project is

Portfolio differentiator for Ajay's move into product-company data-platform roles: proof of AI-native data engineering. It generalizes work he did at UBS (a custom MCP server driving an enterprise scheduler migration) into an open-source MCP server for lakehouse operations. **Audience: hiring managers, interviewers, and real users via PyPI.** Small, sharp, and safe beats feature-rich.

## Non-negotiables

- **Read-only by default is the product.** Every tool must enforce row limits, allowlisted roots, and no-write semantics; tests prove the safety properties.
- No JVM/Spark dependency — delta-rs (`deltalake`) + DuckDB only. `uvx lakehouse-mcp` must just work.
- Never let the README claim something the code doesn't do; the roadmap tracks reality.

## Stack (decided — don't relitigate without asking)

- Python 3.12, managed with `uv`; official `mcp` Python SDK (FastMCP server API)
- `deltalake` (delta-rs) for table metadata/history, DuckDB for query execution
- pytest, ruff, GitHub Actions; publish to PyPI as `lakehouse-mcp`

## Design notes

- Tools: list_tables, get_schema, table_history, query (read-only SQL, row-limited, time-travel aware), dq_results, job_runs (Airflow REST first).
- Demo target is a locally built Streamhouse lakehouse (~/job-switch/projects/streamhouse), but nothing may hard-depend on it.
- Query safety: reject non-SELECT statements before execution; cap rows and bytes; never interpolate raw paths outside allowlisted roots.

## Conventions

- Conventional Commits; imperative mood; body explains why.
- Never commit or push without Ajay's explicit ask.
- Comment the why, not the what.

## Roadmap

P1 core read tools → P2 history/time travel → P3 DQ + job runs → P4 PyPI + demo → P5 hardening. Each phase lands tested and documented before the next starts.
