"""
Register and serve the neoantigen flow deployment.

Wraps neoantigen_flow with simple string parameters so Prefect can
generate a clean deployment schema for the UI form.

Samplesheet parameters accept either:
  - An S3 URI (s3://bucket/key) — content is fetched automatically
  - Raw CSV text pasted directly into the UI form

Resume seeding:
  Pass a Seqera workflow ID into any of the per-pipeline resume fields
  (resume_sarek, resume_hlatyping, etc.) to skip or resume that pipeline.
  Leave a field blank to launch that pipeline fresh.
"""
from __future__ import annotations

import boto3
from prefect import flow

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


def _seed_resumes(resume_map: dict[str, str]) -> dict:
    """Build a resume_ids dict from a {pipeline_name: workflow_id} map.

    Returns {pipeline_name: {workflow_id, session_id, launch_id}} for all
    non-empty entries. Passed directly to NeoantigenInputs.resume_ids so
    run_pipeline receives it as an explicit parameter rather than relying on
    module-level shared state (which breaks across Prefect task boundaries).
    """
    entries = {k: v.strip() for k, v in resume_map.items() if v and v.strip()}
    if not entries:
        return {}
    cfg = SeqeraConfig()
    client = SeqeraClient(token=cfg.token, workspace_id=cfg.workspace_id)
    resume_ids = {}
    for pipeline_name, workflow_id in entries.items():
        info = client.get_workflow_session_info(workflow_id)
        resume_ids[pipeline_name] = {
            "workflow_id": workflow_id,
            "session_id": info["session_id"],
            "launch_id": info["launch_id"],
        }
        session_hint = f"session={info['session_id'][:8]}..." if info["session_id"] else "session unavailable"
        print(f"Resume seeded: {pipeline_name} → {workflow_id} ({session_hint})")
    return resume_ids


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
    resume_sarek: str = "",
    resume_hlatyping: str = "",
    resume_rnaseq: str = "",
    resume_vcf_expression_annotator: str = "",
    resume_epitopeprediction: str = "",
    resume_purecn: str = "",
    resume_post_processing: str = "",
) -> str:
    resume_ids = _seed_resumes({
        "nf-core/sarek": resume_sarek,
        "hlatyping": resume_hlatyping,
        "nf-core/rnaseq": resume_rnaseq,
        "vcf-expression-annotator": resume_vcf_expression_annotator,
        "nf-core/epitopeprediction": resume_epitopeprediction,
        "PureCN": resume_purecn,
        "post-processing": resume_post_processing,
    })
    inputs = NeoantigenInputs(
        patient_id=patient_id,
        wes_samplesheet_csv=_resolve_csv(wes_samplesheet_csv),
        hlatyping_samplesheet_csv=_resolve_csv(hlatyping_samplesheet_csv),
        rnaseq_samplesheet_csv=_resolve_csv(rnaseq_samplesheet_csv),
        tumor_sample_name=tumor_sample_name or f"{patient_id}_T",
        normal_sample_name=normal_sample_name or f"{patient_id}_N",
        sex=sex,
        run_tag=run_tag,
        resume_ids=resume_ids,
    )
    return neoantigen_flow.fn(inputs=inputs)


if __name__ == "__main__":
    neoantigen_flow_deploy.serve(
        name="neoantigen-prediction",
        tags=["neoantigen"],
    )
