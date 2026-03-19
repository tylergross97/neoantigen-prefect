"""
Register and serve the neoantigen flow deployment.

Wraps neoantigen_flow with simple string parameters so Prefect can
generate a clean deployment schema for the UI form.
"""
from __future__ import annotations

from prefect import flow

from neoantigen_flow import NeoantigenInputs, neoantigen_flow


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
    tumor_sample_name: str,
    normal_sample_name: str,
    sex: str = "XX",
    run_tag: str = "",
) -> str:
    inputs = NeoantigenInputs(
        patient_id=patient_id,
        wes_samplesheet_csv=wes_samplesheet_csv,
        hlatyping_samplesheet_csv=hlatyping_samplesheet_csv,
        rnaseq_samplesheet_csv=rnaseq_samplesheet_csv,
        tumor_sample_name=tumor_sample_name,
        normal_sample_name=normal_sample_name,
        sex=sex,
        run_tag=run_tag,
    )
    return neoantigen_flow(inputs=inputs)


if __name__ == "__main__":
    neoantigen_flow_deploy.serve(
        name="neoantigen-prediction",
        tags=["neoantigen"],
    )
