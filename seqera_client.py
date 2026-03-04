"""
Low-level Seqera Platform REST API client.

Wraps the endpoints needed to:
  - Create and upload a Dataset (used as pipeline --input)
  - Launch a pipeline run
  - Poll a run's status
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx


_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"}


class SeqeraClient:
    """Thin synchronous wrapper around the Seqera Platform REST API."""

    def __init__(
        self,
        token: str,
        workspace_id: str,
        api_url: str = "https://api.cloud.seqera.io",
        timeout: float = 30.0,
    ) -> None:
        self.workspace_id = workspace_id
        self._base = api_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _workspace_url(self, path: str) -> str:
        """URL scoped under /workspaces/{id}."""
        return f"{self._base}/workspaces/{self.workspace_id}{path}"

    def _url(self, path: str) -> str:
        """Top-level API URL (not workspace-scoped)."""
        return f"{self._base}{path}"

    # ------------------------------------------------------------------
    # Dataset API
    # ------------------------------------------------------------------

    def _get_dataset_id_by_name(self, name: str) -> str | None:
        """Return the dataset ID for the given name, or None if not found."""
        resp = httpx.get(
            self._workspace_url("/datasets"),
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        for ds in resp.json().get("datasets", []):
            if ds["name"] == name:
                return str(ds["id"])
        return None

    def create_dataset(self, name: str, description: str = "") -> str:
        """
        Create an empty dataset and return its ID.

        POST /workspaces/{id}/datasets
        If a dataset with this name already exists (409), return its existing ID.
        """
        resp = httpx.post(
            self._workspace_url("/datasets"),
            headers=self._headers(),
            json={"name": name, "description": description},
            timeout=self._timeout,
        )
        if resp.status_code == 409:
            existing_id = self._get_dataset_id_by_name(name)
            if existing_id:
                return existing_id
        resp.raise_for_status()
        return str(resp.json()["dataset"]["id"])

    def upload_dataset(self, dataset_id: str, csv_content: str) -> None:
        """
        Upload CSV content to an existing dataset.

        POST /workspaces/{id}/datasets/{datasetId}/upload?header=true
        """
        resp = httpx.post(
            self._workspace_url(f"/datasets/{dataset_id}/upload"),
            params={"header": "true"},
            headers={"Authorization": f"Bearer {self._token}"},
            files={"file": ("samplesheet.csv", csv_content.encode("utf-8"), "text/csv")},
            timeout=60.0,
        )
        resp.raise_for_status()

    def get_dataset_download_url(self, dataset_id: str) -> str:
        """
        Return the HTTPS download URL for the latest version of a dataset.

        GET /workspaces/{id}/datasets/{datasetId}/versions?mimeType=text/csv

        Returns a URL ending in .csv that:
          - passes nf-schema's ^\S+\.csv$ pattern validation
          - is accessible by the nf-tower Nextflow plugin (handles auth automatically)
        """
        resp = httpx.get(
            self._workspace_url(f"/datasets/{dataset_id}/versions"),
            params={"mimeType": "text/csv"},
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        versions = resp.json().get("versions", [])
        if not versions:
            raise RuntimeError(f"No versions found for dataset {dataset_id}")
        return versions[-1]["url"]

    # ------------------------------------------------------------------
    # Pipeline launch API
    # ------------------------------------------------------------------

    def get_pipeline_launch_config(self, pipeline_id: int) -> dict[str, Any]:
        """
        Fetch the saved launch configuration for a launchpad pipeline.

        GET /pipelines/{pipelineId}/launch?workspaceId={id}

        Returns the launch config dict (contains launchId, computeEnv, revision, etc.).
        """
        resp = httpx.get(
            self._url(f"/pipelines/{pipeline_id}/launch"),
            params={"workspaceId": self.workspace_id},
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()["launch"]

    def launch_pipeline(
        self,
        pipeline_id: int,
        compute_env_id: str,
        work_dir: str,
        params: dict[str, Any],
        run_name: str,
        credentials_id: str | None = None,
        config_profiles: list[str] | None = None,
        resume: bool = False,
        session_id: str | None = None,
        pre_run_script: str | None = None,
    ) -> str:
        """
        Launch a pipeline and return the workflow ID (run ID).

        Flow:
          1. GET /pipelines/{id}/launch  — fetch saved launch config (launchId, revision, configText)
          2. POST /workflow/launch?workspaceId={id}  — submit the run

        Returns the workflowId string.
        """
        # Step 1: fetch the pipeline's saved launch config
        lc = self.get_pipeline_launch_config(pipeline_id)
        launch_id = lc["id"]
        revision = lc.get("revision") or ""
        config_text = lc.get("configText") or ""

        # Use caller-supplied profiles if provided; otherwise use empty list.
        # We deliberately do NOT inherit configProfiles from the launchpad template
        # (which often contains "test") — our params already specify real data.
        profiles = config_profiles if config_profiles is not None else []

        # Step 2: build the launch body.
        # paramsText is a JSON string (not a nested object).
        launch_body: dict[str, Any] = {
            "id": launch_id,
            "computeEnvId": compute_env_id,
            "pipeline": lc.get("pipeline", ""),
            "workDir": work_dir,
            "revision": revision,
            "configProfiles": profiles,
            "configText": config_text,
            "paramsText": json.dumps(params),
            "pullLatest": False,
            "stubRun": False,
            "userSecrets": [],
            "workspaceSecrets": [],
            "resume": resume,
        }
        if run_name:
            launch_body["runName"] = run_name
        if credentials_id:
            launch_body["credentialsId"] = credentials_id
        if session_id:
            launch_body["sessionId"] = session_id
        if pre_run_script:
            launch_body["preRunScript"] = pre_run_script

        resp = httpx.post(
            self._url("/workflow/launch"),
            params={"workspaceId": self.workspace_id},
            headers=self._headers(),
            json={"launch": launch_body},
            timeout=self._timeout,
        )
        if not resp.is_success:
            raise RuntimeError(
                f"Launch failed {resp.status_code}: {resp.text}\n"
                f"Body sent: {json.dumps({'launch': launch_body}, indent=2)}"
            )
        return str(resp.json()["workflowId"])

    # ------------------------------------------------------------------
    # Run status API
    # ------------------------------------------------------------------

    def get_run_status(self, workflow_id: str) -> tuple[str, str | None]:
        """
        Return (status, exit_status) for a workflow run.

        GET /workflow/{workflowId}?workspaceId={id}
        """
        resp = httpx.get(
            self._url(f"/workflow/{workflow_id}"),
            params={"workspaceId": self.workspace_id},
            headers=self._headers(),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        wf = resp.json()["workflow"]
        return wf["status"], wf.get("exitStatus")

    def poll_until_complete(
        self,
        workflow_id: str,
        pipeline_name: str = "",
        poll_interval: int = 60,
        max_consecutive_errors: int = 5,
        logger: Any = None,
    ) -> str:
        """
        Block until the run reaches a terminal state.

        Returns the final status string ("SUCCEEDED").
        Raises RuntimeError if the run fails or is cancelled.
        Tolerates up to `max_consecutive_errors` consecutive API failures
        before re-raising (handles transient network issues).
        """
        label = pipeline_name or workflow_id
        consecutive_errors = 0

        while True:
            try:
                status, exit_status = self.get_run_status(workflow_id)
                consecutive_errors = 0  # reset on success
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                consecutive_errors += 1
                if logger:
                    logger.warning(
                        f"[{label}] API error while polling ({consecutive_errors}/"
                        f"{max_consecutive_errors}): {exc}"
                    )
                if consecutive_errors >= max_consecutive_errors:
                    raise
                time.sleep(poll_interval)
                continue

            if logger:
                logger.info(f"[{label}] status={status}")

            if status in _TERMINAL_STATES:
                if status != "SUCCEEDED":
                    raise RuntimeError(
                        f"Pipeline '{label}' (run {workflow_id}) ended with "
                        f"status={status}, exitStatus={exit_status}"
                    )
                return status

            time.sleep(poll_interval)
