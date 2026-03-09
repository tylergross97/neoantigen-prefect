"""
CLI entrypoint for the neoantigen prediction flow.

Usage:
    python run_flow.py
        --patient-id PID_001
        --wes-samplesheet /path/to/wes.csv
        --rnaseq-samplesheet /path/to/rnaseq.csv
        --tumor-sample TUMOR_001
        [--run-tag my-tag-20250101]

Pipeline IDs default to values in config.py but can be overridden via flags or env vars:
    PIPELINE_SAREK_ID, PIPELINE_HLATYPING_ID, PIPELINE_RNASEQ_ID,
    PIPELINE_VCF_EXPR_ID, PIPELINE_EPITOPEPREDICTION_ID, PIPELINE_PURECN_ID,
    PIPELINE_POST_PROCESSING_ID
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from config import PipelineIds, SeqeraConfig
from neoantigen_flow import NeoantigenInputs, neoantigen_flow
import tasks  # imported for _LAST_WORKFLOW_IDS pre-seeding


def _int_or_env(arg_val: int | None, env_key: str) -> int | None:
    if arg_val is not None:
        return arg_val
    raw = os.getenv(env_key)
    return int(raw) if raw else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch the neoantigen Prefect flow against Seqera Platform"
    )

    # Required inputs
    parser.add_argument("--patient-id", required=True, help="Patient/sample identifier")
    parser.add_argument(
        "--wes-samplesheet",
        required=True,
        type=Path,
        help="Path to WES samplesheet CSV (nf-core/sarek format)",
    )
    parser.add_argument(
        "--hlatyping-samplesheet",
        required=True,
        type=Path,
        help="Path to hlatyping samplesheet CSV (sample,fastq_1,fastq_2,seq_type — normal reads only)",
    )
    parser.add_argument(
        "--rnaseq-samplesheet",
        required=True,
        type=Path,
        help="Path to RNA-seq samplesheet CSV (nf-core/rnaseq format)",
    )
    parser.add_argument(
        "--tumor-sample",
        required=True,
        help="Tumor sample name as it appears in the sarek samplesheet",
    )
    parser.add_argument(
        "--normal-sample",
        required=True,
        help="Normal sample name as it appears in the sarek samplesheet (used to build vs-name output paths)",
    )
    parser.add_argument(
        "--sex",
        default="XX",
        choices=["XX", "XY"],
        help="Biological sex of the patient (default: XX)",
    )

    # Optional
    parser.add_argument("--run-tag", default="", help="Short tag appended to run names")
    parser.add_argument(
        "--resume-workflow",
        action="append",
        default=[],
        metavar="PIPELINE_NAME:WORKFLOW_ID",
        help=(
            "Pre-seed a pipeline to resume from an existing Seqera workflow run. "
            "Format: 'nf-core/sarek:5Zpxj5YTfyiacx'. "
            "Can be specified multiple times. "
            "Resume uses GET /workflow/{id}/launch to obtain the correct entity launchId."
        ),
    )

    # Pipeline ID overrides (fall back to defaults in config.py)
    id_group = parser.add_argument_group("Pipeline ID overrides (optional)")
    id_group.add_argument("--sarek-id", type=int)
    id_group.add_argument("--hlatyping-id", type=int)
    id_group.add_argument("--rnaseq-id", type=int)
    id_group.add_argument("--vcf-expr-id", type=int)
    id_group.add_argument("--epitopeprediction-id", type=int)
    id_group.add_argument("--purecn-id", type=int)
    id_group.add_argument("--post-processing-id", type=int)

    args = parser.parse_args()

    # Read samplesheet files
    wes_csv = args.wes_samplesheet.read_text()
    hlatyping_csv = args.hlatyping_samplesheet.read_text()
    rnaseq_csv = args.rnaseq_samplesheet.read_text()

    # Build PipelineIds — CLI args override env vars, env vars override config.py defaults
    defaults = PipelineIds()
    pipeline_ids = PipelineIds(
        sarek=_int_or_env(args.sarek_id, "PIPELINE_SAREK_ID") or defaults.sarek,
        hlatyping=_int_or_env(args.hlatyping_id, "PIPELINE_HLATYPING_ID") or defaults.hlatyping,
        rnaseq=_int_or_env(args.rnaseq_id, "PIPELINE_RNASEQ_ID") or defaults.rnaseq,
        vcf_expression_annotator=_int_or_env(args.vcf_expr_id, "PIPELINE_VCF_EXPR_ID") or defaults.vcf_expression_annotator,
        epitopeprediction=_int_or_env(args.epitopeprediction_id, "PIPELINE_EPITOPEPREDICTION_ID") or defaults.epitopeprediction,
        purecn=_int_or_env(args.purecn_id, "PIPELINE_PURECN_ID") or defaults.purecn,
        post_processing=_int_or_env(args.post_processing_id, "PIPELINE_POST_PROCESSING_ID") or defaults.post_processing,
    )

    # Pre-seed workflow IDs for resume. Eagerly fetch sessionId + launchId now
    # (while the runs are accessible) so that tasks.py can bypass the stale
    # GET /workflow/{id}/launch call at launch time.
    if args.resume_workflow:
        from seqera_client import SeqeraClient
        _seed_client = SeqeraClient(
            token=SeqeraConfig().token,
            workspace_id=SeqeraConfig().workspace_id,
        )
    for entry in args.resume_workflow:
        if ":" not in entry:
            sys.exit(f"--resume-workflow must be 'PIPELINE_NAME:WORKFLOW_ID', got: {entry!r}")
        pipeline_name, workflow_id = entry.split(":", 1)
        info = _seed_client.get_workflow_session_info(workflow_id)
        tasks._LAST_WORKFLOW_IDS[pipeline_name] = {
            "workflow_id": workflow_id,
            "session_id": info["session_id"],
            "launch_id": info["launch_id"],
        }
        session_hint = f"session={info['session_id'][:8]}..." if info["session_id"] else "session unavailable"
        print(f"  Resume seeded: {pipeline_name} → {workflow_id} ({session_hint})")

    inputs = NeoantigenInputs(
        patient_id=args.patient_id,
        wes_samplesheet_csv=wes_csv,
        hlatyping_samplesheet_csv=hlatyping_csv,
        rnaseq_samplesheet_csv=rnaseq_csv,
        tumor_sample_name=args.tumor_sample,
        normal_sample_name=args.normal_sample,
        sex=args.sex,
        run_tag=args.run_tag,
    )

    result = neoantigen_flow(
        inputs=inputs,
        seqera_cfg=SeqeraConfig(),
        pipeline_ids=pipeline_ids,
    )

    print(f"\nDone. Final outputs: {result}")


if __name__ == "__main__":
    main()
