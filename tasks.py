"""
Prefect tasks for interacting with Seqera Platform.

Two primary tasks:
  - create_and_upload_dataset  → upload a CSV samplesheet as a Seqera Dataset
  - run_pipeline               → launch a pipeline and block until it completes

Both tasks are designed to be submitted with .submit() in the flow so that
independent steps run in parallel via Prefect's task runner.
"""
from __future__ import annotations

import re
import time
from typing import Any

from prefect import get_run_logger, task
from config import SeqeraConfig
from seqera_client import SeqeraClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_run_name(pipeline_name: str, tag: str, max_len: int = 40) -> str:
    """
    Build a Seqera-compatible run name (alphanumeric + hyphens, ≤ 40 chars).
    Seqera enforces: ^[a-z0-9]([a-z0-9\-]{0,38})[a-z0-9]$
    """
    raw = f"{pipeline_name}-{tag}".lower()
    sanitized = re.sub(r"[^a-z0-9\-]", "-", raw)
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    return sanitized[:max_len].strip("-")


# ---------------------------------------------------------------------------
# Task: create + upload a Seqera Dataset
# ---------------------------------------------------------------------------

@task(
    name="create-dataset",
    task_run_name="create-dataset-{name}",
    retries=3,
    retry_delay_seconds=30,
)
def create_and_upload_dataset(
    cfg: SeqeraConfig,
    name: str,
    csv_content: str,
) -> str:
    """
    Create a named Seqera Dataset, upload the CSV content, and return the
    dataset:// URI for use as a pipeline --input param.
    """
    logger = get_run_logger()
    client = SeqeraClient(
        token=cfg.token,
        workspace_id=cfg.workspace_id,
        api_url=cfg.api_url,
    )
    dataset_id = client.create_dataset(name, description="Auto-created by Prefect")
    client.upload_dataset(dataset_id, csv_content)
    url = client.get_dataset_download_url(dataset_id)
    logger.info(f"Dataset '{name}' created (id={dataset_id}) → {url}")
    return url


# ---------------------------------------------------------------------------
# Task: launch pipeline and poll until complete
# ---------------------------------------------------------------------------

# Maps pipeline_name → workflowId of the last failed run.
# Used to pass resume_from_workflow_id on the Prefect retry attempt.
# Persists for the lifetime of the Python process (i.e. one flow run).
_LAST_WORKFLOW_IDS: dict[str, str] = {}


@task(
    name="run-pipeline",
    task_run_name="run-{pipeline_name}-{run_tag}",
    retries=1,                # retry the entire launch+poll once on unexpected failure
    retry_delay_seconds=120,
    timeout_seconds=172_800,  # 48 h hard ceiling
)
def run_pipeline(
    cfg: SeqeraConfig,
    pipeline_id: int,
    pipeline_name: str,
    run_tag: str,
    params: dict[str, Any],
    config_profiles: list[str] | None = None,
    launch_delay_seconds: int = 0,
    pre_run_script: str | None = None,
    revision: str | None = None,
    config_text_extra: str | None = None,
) -> str:
    """
    Launch a Seqera Platform pipeline and block until it completes.

    On the first Prefect attempt: launches fresh.
    On the Prefect retry attempt: if a workflowId was captured from the failed
    run, uses GET /workflow/{id}/launch to obtain the workflow entity launchId
    and embedded sessionId, then launches with resume=True so Nextflow skips
    already-completed tasks.

    The workflow entity launchId is required for resume — Seqera rejects
    resume=true when the launchId has entity=pipeline (returns 400).

    Returns the Seqera workflow ID of the completed run. Raises RuntimeError
    if the run ends in any non-SUCCEEDED terminal state.
    """
    logger = get_run_logger()

    client = SeqeraClient(
        token=cfg.token,
        workspace_id=cfg.workspace_id,
        api_url=cfg.api_url,
    )

    if launch_delay_seconds:
        time.sleep(launch_delay_seconds)

    prev_workflow_id = _LAST_WORKFLOW_IDS.get(pipeline_name)
    run_name = _safe_run_name(pipeline_name, run_tag)

    if prev_workflow_id:
        logger.info(
            f"Resuming '{pipeline_name}' as run '{run_name}' "
            f"(from workflow {prev_workflow_id})"
        )
    else:
        logger.info(f"Launching '{pipeline_name}' as run '{run_name}' (pipeline_id={pipeline_id})")

    def _launch(resume_from: str | None) -> str:
        return client.launch_pipeline(
            pipeline_id=pipeline_id,
            compute_env_id=cfg.compute_env_id,
            work_dir=cfg.work_dir,
            params=params,
            run_name=run_name,
            credentials_id=cfg.credentials_id,
            config_profiles=config_profiles,
            pre_run_script=pre_run_script,
            revision=revision,
            config_text_extra=config_text_extra,
            resume_from_workflow_id=resume_from,
        )

    try:
        workflow_id = _launch(prev_workflow_id)
    except RuntimeError as exc:
        if prev_workflow_id and "400" in str(exc):
            logger.warning(
                "Resume launch rejected by Seqera (400) — falling back to fresh start"
            )
            _LAST_WORKFLOW_IDS.pop(pipeline_name, None)
            workflow_id = _launch(None)
        else:
            raise

    seqera_url = (
        f"https://cloud.seqera.io/orgs/tyler-gross-org-4405/workspaces/"
        f"{cfg.workspace_id}/watch/{workflow_id}"
    )
    logger.info(f"Run launched: {workflow_id}\n  Monitor: {seqera_url}")

    try:
        client.poll_until_complete(
            workflow_id=workflow_id,
            pipeline_name=pipeline_name,
            poll_interval=60,
            logger=logger,
        )
    except RuntimeError:
        _LAST_WORKFLOW_IDS[pipeline_name] = workflow_id
        logger.warning(f"Captured workflowId={workflow_id} for resume on retry")
        raise

    _LAST_WORKFLOW_IDS.pop(pipeline_name, None)  # clear on success
    logger.info(f"'{pipeline_name}' SUCCEEDED (run {workflow_id})")
    return workflow_id
