"""
Register and serve the neoantigen flow deployment.

Wraps neoantigen_flow with simple string parameters so Prefect can
generate a clean deployment schema for the UI form.

Samplesheet parameters accept either:
  - An S3 URI (s3://bucket/key) — content is fetched automatically
  - Raw CSV text pasted directly into the UI form
"""
from __future__ import annotations

import boto3
from prefect import flow

from neoantigen_flow import NeoantigenInputs, neoantigen_flow


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
) -> str:
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
    return neoantigen_flow(inputs=inputs)


if __name__ == "__main__":
    neoantigen_flow_deploy.serve(
        name="neoantigen-prediction",
        tags=["neoantigen"],
    )
