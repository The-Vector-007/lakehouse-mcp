"""The MCP server: six read-only tools over a Delta lakehouse.

Run it:

    uvx lakehouse-mcp --root /path/to/warehouse

Or point an MCP client at it. Every tool goes through `Config.resolve`, so a path
outside the roots you pass on the command line is refused no matter how it is
spelled.
"""

import argparse
import sys

from mcp.server.fastmcp import FastMCP

from lakehouse_mcp.config import AccessDenied, Config
from lakehouse_mcp.jobs import AirflowConfig, OrchestratorUnavailable
from lakehouse_mcp.jobs import job_runs as _job_runs
from lakehouse_mcp.query import read_dq_results, run_query
from lakehouse_mcp.safety import UnsafeQuery
from lakehouse_mcp.tables import find_tables, get_schema, table_history

mcp = FastMCP("lakehouse")

# Set by main(). Kept module-level because FastMCP tools are plain functions and
# threading a config through every signature would put it in the tool schema, where
# an agent would try to supply it.
_config = Config()


def configure(config: Config) -> None:
    global _config
    _config = config


def _fail(exc: Exception) -> dict:
    """Return the refusal as data.

    An agent handles "you may not do that, here is why" far better than an
    exception, which it tends to retry verbatim.
    """
    return {"error": type(exc).__name__, "message": str(exc)}


@mcp.tool()
def list_tables() -> dict:
    """List every Delta table under the configured lakehouse roots."""
    try:
        return {"tables": [{"name": t.name, "path": t.path} for t in find_tables(_config)]}
    except AccessDenied as exc:
        return _fail(exc)


@mcp.tool()
def schema(path: str, version: int | None = None) -> dict:
    """Column names, types, nullability and partition columns for one table.

    Pass `version` to see the schema as it was at that Delta version.
    """
    try:
        return get_schema(_config, path, version=version)
    except (AccessDenied, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def history(path: str, limit: int = 20) -> dict:
    """Recent Delta commits: version, timestamp, operation and row metrics.

    Use this to answer "what changed, and when?" before reaching for a query.
    """
    try:
        return {"history": table_history(_config, path, limit=limit)}
    except (AccessDenied, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def query(
    sql: str,
    limit: int | None = None,
    table: str | None = None,
    version: int | None = None,
) -> dict:
    """Run one read-only SELECT across the lakehouse.

    Every discoverable table is registered under its directory name. Anything that
    is not a single SELECT is refused. Results are row-capped, and `truncated`
    tells you when the cap bit.

    For time travel, pass `table` and `version` together to pin that one table to a
    historical version and run the same query against it.
    """
    try:
        return run_query(_config, sql, limit=limit, table=table, version=version)
    except (UnsafeQuery, AccessDenied, FileNotFoundError) as exc:
        return _fail(exc)


@mcp.tool()
def dq_results(path: str | None = None, limit: int = 50) -> dict:
    """Latest data-quality check outcomes, newest first.

    Answers "did last night's load degrade?" without anyone opening a notebook.
    """
    try:
        return read_dq_results(_config, table_path=path, limit=limit)
    except (AccessDenied, FileNotFoundError, UnsafeQuery) as exc:
        return _fail(exc)


@mcp.tool()
def job_runs(dag_id: str | None = None, limit: int = 20) -> dict:
    """Recent orchestrator runs and their state, newest first.

    Answers the question that follows every data-quality alert: the numbers look
    wrong, did the job even run? Pass a `dag_id` to also get the per-task
    breakdown of the latest run, which is the "which step broke?" view.

    Needs AIRFLOW_API_URL set; without it you get a message saying so.
    """
    try:
        return _job_runs(AirflowConfig.from_env(), dag_id=dag_id, limit=limit)
    except OrchestratorUnavailable as exc:
        return _fail(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only MCP server for a Delta lakehouse.")
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="A lakehouse root the server may read. Repeatable. Nothing outside is reachable.",
    )
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args(argv)

    config = Config.from_env(args.root or None)
    if not config.roots:
        parser.error("at least one --root is required (or set LAKEHOUSE_ROOTS)")
    if args.max_rows:
        config = Config(
            roots=config.roots,
            max_rows=args.max_rows,
            max_bytes=config.max_bytes,
            timeout_seconds=config.timeout_seconds,
        )

    configure(config)
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
