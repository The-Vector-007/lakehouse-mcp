"""Orchestrator run status, read from Airflow's REST API.

The question this answers is the one that follows every data-quality alert: the
numbers look wrong, did the job even run? Schema and history describe the table;
this describes the thing that wrote it.

Talks to the REST API rather than Airflow's metadata database on purpose. The
database schema is Airflow's private business and changes between minor versions,
while the API is versioned and works the same against a local install or a managed
deployment. The cost is that Airflow has to be up, which is why every failure here
comes back as a readable message rather than an exception.

No new dependency: urllib is enough for three GETs.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_TIMEOUT = 10


class OrchestratorUnavailable(Exception):
    """Airflow could not be reached, or refused us."""


@dataclass(frozen=True)
class AirflowConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    timeout: int = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "AirflowConfig":
        return cls(
            base_url=os.getenv("AIRFLOW_API_URL", "").rstrip("/"),
            username=os.getenv("AIRFLOW_USERNAME", ""),
            password=os.getenv("AIRFLOW_PASSWORD", ""),
            timeout=int(os.getenv("AIRFLOW_TIMEOUT", DEFAULT_TIMEOUT)),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


def _fetch(config: AirflowConfig, path: str) -> dict:
    if not config.configured:
        raise OrchestratorUnavailable(
            "no Airflow API configured; set AIRFLOW_API_URL "
            "(for example http://localhost:8080/api/v1)"
        )

    request = urllib.request.Request(f"{config.base_url}{path}")
    if config.username:
        token = base64.b64encode(f"{config.username}:{config.password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")

    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # 401 and 403 are the common ones and mean something a caller can act on,
        # so say which rather than collapsing every status into "failed".
        raise OrchestratorUnavailable(
            f"Airflow returned {exc.code} for {path}: {exc.reason}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OrchestratorUnavailable(
            f"could not reach Airflow at {config.base_url}: {exc}"
        ) from exc


def job_runs(config: AirflowConfig, *, dag_id: str | None = None, limit: int = 20) -> dict:
    """Recent DAG runs, newest first, with per-task state when a dag_id is given.

    Without a dag_id this lists runs across every DAG, which is the "what has the
    platform been doing?" view. With one, it adds the task breakdown, which is the
    "which step broke?" view.
    """
    if dag_id:
        payload = _fetch(
            config,
            f"/dags/{dag_id}/dagRuns?order_by=-execution_date&limit={limit}",
        )
    else:
        payload = _fetch(config, f"/dags/~/dagRuns?order_by=-execution_date&limit={limit}")

    runs = [
        {
            "dag_id": run.get("dag_id"),
            "run_id": run.get("dag_run_id"),
            "state": run.get("state"),
            "run_type": run.get("run_type"),
            "logical_date": run.get("logical_date") or run.get("execution_date"),
            "start_date": run.get("start_date"),
            "end_date": run.get("end_date"),
        }
        for run in payload.get("dag_runs", [])
    ]

    result = {"runs": runs, "total": payload.get("total_entries", len(runs))}

    if dag_id and runs:
        latest = runs[0]["run_id"]
        tasks = _fetch(config, f"/dags/{dag_id}/dagRuns/{latest}/taskInstances")
        result["latest_run_tasks"] = [
            {
                "task_id": task.get("task_id"),
                "state": task.get("state"),
                "try_number": task.get("try_number"),
                "duration": task.get("duration"),
            }
            for task in tasks.get("task_instances", [])
        ]
    return result
