"""serve_flow.py — with S3 error logging for diagnosis."""
from __future__ import annotations
import sys
import traceback


def _log_to_s3(message: str) -> None:
    try:
        import boto3
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket="neoantigen-prefect-evjnnnoto",
            Key="serve_flow.log",
            Body=message.encode(),
        )
    except Exception as e:
        print(f"S3 log failed: {e}", file=sys.stderr, flush=True)


def main() -> None:
    log = ["serve_flow.py starting\n"]
    try:
        log.append("importing prefect...\n")
        from prefect import flow
        log.append("importing neoantigen_flow...\n")
        from neoantigen_flow import NeoantigenInputs, neoantigen_flow
        log.append("imports OK\n")

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

        log.append("calling serve()...\n")
        _log_to_s3("".join(log))
        neoantigen_flow_deploy.serve(
            name="neoantigen-prediction",
            tags=["neoantigen"],
        )

    except Exception:
        tb = traceback.format_exc()
        log.append(f"EXCEPTION:\n{tb}\n")
        msg = "".join(log)
        print(msg, file=sys.stderr, flush=True)
        _log_to_s3(msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
