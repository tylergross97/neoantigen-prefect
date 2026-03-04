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

    Cached by (cfg, name, csv_content) so identical uploads are skipped on
    flow reruns.
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
    resume: bool = False,
) -> str:
    """
    Launch a Seqera Platform pipeline and block until it completes.

    Returns the Seqera workflow ID of the completed run. Raises RuntimeError
    if the run ends in any non-SUCCEEDED terminal state.

    Args:
        cfg:             Seqera workspace + credentials config.
        pipeline_id:     Integer pipeline ID from the Seqera launchpad.
        pipeline_name:   Human-readable name used in logs and the run name.
        run_tag:         Short tag appended to the run name (e.g. patient ID + date).
        params:          Nextflow params dict (maps to --param_name values).
        config_profiles: Optional list of Nextflow config profile names.
        resume:          Pass True to launch with -resume (re-use cached Nextflow work).
    """
    logger = get_run_logger()

    client = SeqeraClient(
        token=cfg.token,
        workspace_id=cfg.workspace_id,
        api_url=cfg.api_url,
    )

    run_name = _safe_run_name(pipeline_name, run_tag)
    logger.info(f"Launching '{pipeline_name}' as run '{run_name}' (pipeline_id={pipeline_id})")

    workflow_id = client.launch_pipeline(
        pipeline_id=pipeline_id,
        compute_env_id=cfg.compute_env_id,
        work_dir=cfg.work_dir,
        params=params,
        run_name=run_name,
        credentials_id=cfg.credentials_id,
        config_profiles=config_profiles,
        resume=resume,
    )

    seqera_url = (
        f"https://cloud.seqera.io/orgs/tyler-gross-org-4405/workspaces/"
        f"{cfg.workspace_id}/watch/{workflow_id}"
    )
    logger.info(f"Run launched: {workflow_id}\n  Monitor: {seqera_url}")

    client.poll_until_complete(
        workflow_id=workflow_id,
        pipeline_name=pipeline_name,
        poll_interval=60,
        logger=logger,
    )

    logger.info(f"'{pipeline_name}' SUCCEEDED (run {workflow_id})")
    return workflow_id
