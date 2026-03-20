"""
Register and serve the neoantigen flow deployment.

Wraps neoantigen_flow with simple string parameters so Prefect can
generate a clean deployment schema for the UI form.

Samplesheet parameters accept either:
  - An S3 URI (s3://bucket/key) — content is fetched automatically
  - Raw CSV text pasted directly into the UI form

Resume seeding:
  Pass resume_workflows as a comma-separated list of PIPELINE_NAME:WORKFLOW_ID pairs
  to skip or resume pipelines that already ran. Example:
    "nf-core/sarek:3gly8S5RdElh8y,hlatyping:u3c6i68W4BrLw"
  Pipeline name keys: nf-core/sarek, hlatyping, nf-core/rnaseq,
    vcf-expression-annotator, nf-core/epitopeprediction, PureCN, post-processing
"""
from __future__ import annotations

import boto3
from prefect import flow

import tasks
from config import SeqeraConfig
from neoantigen_flow import NeoantigenInputs, neoantigen_flow
from seqera_client import SeqeraClient


def _resolve_csv(value: str) -> str:
    """Return CSV content from an S3 URI, local file path, or inline CSV text."""
    if value.startswith("s3://"):
        without_scheme = value[5:]
        bucket, _, key = without_scheme.partition("/")
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8")
    if value.startswith("/") or value.startswith("./"):
        with open(value) as f:
            return f.read()
    return value


def _seed_resumes(resume_workflows: str) -> None:
    """Pre-seed tasks._LAST_WORKFLOW_IDS from a comma-separated PIPELINE:WORKFLOW_ID string."""
    if not resume_workflows.strip():
        return
    cfg = SeqeraConfig()
    client = SeqeraClient(token=cfg.token, workspace_id=cfg.workspace_id)
    for entry in resume_workflows.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                f"resume_workflows entries must be 'PIPELINE_NAME:WORKFLOW_ID', got: {entry!r}"
            )
        pipeline_name, workflow_id = entry.split(":", 1)
        info = client.get_workflow_session_info(workflow_id)
        tasks._LAST_WORKFLOW_IDS[pipeline_name] = {
            "workflow_id": workflow_id,
            "session_id": info["session_id"],
            "launch_id": info["launch_id"],
        }
        session_hint = f"session={info['session_id'][:8]}..." if info["session_id"] else "session unavailable"
        print(f"Resume seeded: {pipeline_name} → {workflow_id} ({session_hint})")


@flow(
    name="neoantigen-prediction",
    description="End-to-end neoantigen prediction pipeline orchestrated via Seqera Platform",
    log_prints=True,
)
def neoantigen_flow_deploy(
    patient_id: str,
    wes_samplesheet_csv: str,
    hlatyping_samplesheet_csv: str,
    rnaseq_samplesheet_csv: str,
    sex: str = "XX",
    run_tag: str = "",
    tumor_sample_name: str = "",
    normal_sample_name: str = "",
    resume_workflows: str = "",
) -> str:
    _seed_resumes(resume_workflows)
    inputs = NeoantigenInputs(
        patient_id=patient_id,
        wes_samplesheet_csv=_resolve_csv(wes_samplesheet_csv),
        hlatyping_samplesheet_csv=_resolve_csv(hlatyping_samplesheet_csv),
        rnaseq_samplesheet_csv=_resolve_csv(rnaseq_samplesheet_csv),
        tumor_sample_name=tumor_sample_name or f"{patient_id}_T",
        normal_sample_name=normal_sample_name or f"{patient_id}_N",
        sex=sex,
        run_tag=run_tag,
    )
    return neoantigen_flow.fn(inputs=inputs)


if __name__ == "__main__":
    neoantigen_flow_deploy.serve(
        name="neoantigen-prediction",
        tags=["neoantigen"],
    )
