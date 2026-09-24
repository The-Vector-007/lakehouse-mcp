"""Orchestrator status. The HTTP layer is stubbed; Airflow is not this project's job to run."""

import json
from unittest.mock import patch

import pytest

from lakehouse_mcp.jobs import AirflowConfig, OrchestratorUnavailable, job_runs

RUNS = {
    "dag_runs": [
        {
            "dag_id": "streamhouse_daily",
            "dag_run_id": "manual__2026-09-24",
            "state": "success",
            "run_type": "manual",
            "logical_date": "2026-09-24T00:00:00+00:00",
            "start_date": "2026-09-24T02:00:00+00:00",
            "end_date": "2026-09-24T02:09:00+00:00",
        }
    ],
    "total_entries": 1,
}

TASKS = {
    "task_instances": [
        {"task_id": "refine", "state": "success", "try_number": 1, "duration": 120.0},
        {"task_id": "optimize", "state": "success", "try_number": 1, "duration": 95.0},
        {"task_id": "vacuum", "state": "failed", "try_number": 2, "duration": 30.0},
    ]
}


def _stub(mapping):
    def fake(request, timeout=None):
        url = request.full_url
        body = next(v for k, v in mapping.items() if k in url)

        class Response:
            def read(self):
                return json.dumps(body).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return Response()

    return fake


def test_unconfigured_says_so_instead_of_failing_obscurely():
    with pytest.raises(OrchestratorUnavailable, match="AIRFLOW_API_URL"):
        job_runs(AirflowConfig())


def test_lists_runs_newest_first():
    config = AirflowConfig(base_url="http://localhost:8080/api/v1")
    with patch("urllib.request.urlopen", _stub({"dagRuns": RUNS})):
        result = job_runs(config)

    assert result["total"] == 1
    assert result["runs"][0]["state"] == "success"
    assert result["runs"][0]["dag_id"] == "streamhouse_daily"
    # No dag_id given, so no per-task breakdown: that is the cross-DAG view.
    assert "latest_run_tasks" not in result


def test_a_dag_id_adds_the_task_breakdown():
    """The 'which step broke?' view."""
    config = AirflowConfig(base_url="http://localhost:8080/api/v1")
    with patch("urllib.request.urlopen", _stub({"taskInstances": TASKS, "dagRuns": RUNS})):
        result = job_runs(config, dag_id="streamhouse_daily")

    states = {t["task_id"]: t["state"] for t in result["latest_run_tasks"]}
    assert states == {"refine": "success", "optimize": "success", "vacuum": "failed"}
    assert [t for t in result["latest_run_tasks"] if t["task_id"] == "vacuum"][0]["try_number"] == 2


def test_an_unreachable_airflow_is_a_message_not_a_traceback():
    """An agent handles 'could not reach X' far better than a URLError."""
    import urllib.error

    config = AirflowConfig(base_url="http://localhost:9999/api/v1")

    def boom(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    with (
        patch("urllib.request.urlopen", boom),
        pytest.raises(OrchestratorUnavailable, match="could not reach"),
    ):
        job_runs(config)


def test_auth_failures_name_the_status_code():
    import urllib.error

    config = AirflowConfig(base_url="http://localhost:8080/api/v1", username="u", password="p")

    def denied(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    with (
        patch("urllib.request.urlopen", denied),
        pytest.raises(OrchestratorUnavailable, match="401"),
    ):
        job_runs(config)
