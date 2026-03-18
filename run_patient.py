"""
Convenience launcher: run the neoantigen flow for a single patient by PID.

Usage:
    python run_patient.py PID262622
    python run_patient.py PID147771 --resume-workflow "nf-core/sarek:abc123"

Samplesheets are resolved automatically from samplesheets/{PID}_*.csv.
Sex and sample names are derived from the WES samplesheet.
All --resume-workflow and --*-id flags are forwarded to run_flow.py unchanged.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

# Locate repo root (directory containing this file)
REPO_ROOT = Path(__file__).parent
SAMPLESHEETS_DIR = REPO_ROOT / "samplesheets"


def _parse_sex_from_wes(wes_csv: str) -> str:
    """Return sex (XX/XY) from the first data row of the WES samplesheet."""
    reader = csv.DictReader(io.StringIO(wes_csv))
    for row in reader:
        return row["sex"]
    raise ValueError("WES samplesheet has no data rows")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run neoantigen flow for a patient by PID"
    )
    parser.add_argument("patient_id", help="Patient ID, e.g. PID262622")
    parser.add_argument(
        "--resume-workflow",
        action="append",
        default=[],
        metavar="PIPELINE_NAME:WORKFLOW_ID",
        help=(
            "Pre-seed a pipeline resume. Format: 'PIPELINE_NAME:WORKFLOW_ID'. "
            "Can be specified multiple times."
        ),
    )
    parser.add_argument("--run-tag", default="", help="Short tag appended to run names")

    # Pipeline ID overrides — forwarded directly to run_flow.py
    id_group = parser.add_argument_group("Pipeline ID overrides (optional)")
    id_group.add_argument("--sarek-id", type=int)
    id_group.add_argument("--hlatyping-id", type=int)
    id_group.add_argument("--rnaseq-id", type=int)
    id_group.add_argument("--vcf-expr-id", type=int)
    id_group.add_argument("--epitopeprediction-id", type=int)
    id_group.add_argument("--purecn-id", type=int)
    id_group.add_argument("--post-processing-id", type=int)

    args = parser.parse_args()

    pid = args.patient_id

    wes_path = SAMPLESHEETS_DIR / f"{pid}_wes.csv"
    hla_path = SAMPLESHEETS_DIR / f"{pid}_hlatyping.csv"
    rnaseq_path = SAMPLESHEETS_DIR / f"{pid}_rnaseq.csv"

    for p in (wes_path, hla_path, rnaseq_path):
        if not p.exists():
            sys.exit(f"Missing samplesheet: {p}")

    wes_csv = wes_path.read_text()
    sex = _parse_sex_from_wes(wes_csv)
    tumor_sample = f"{pid}_T"
    normal_sample = f"{pid}_N"

    print(f"Patient : {pid}")
    print(f"Sex     : {sex}")
    print(f"Tumor   : {tumor_sample}")
    print(f"Normal  : {normal_sample}")
    print()

    # Build argv for run_flow.py and hand off
    argv = [
        "run_flow.py",
        "--patient-id", pid,
        "--wes-samplesheet", str(wes_path),
        "--hlatyping-samplesheet", str(hla_path),
        "--rnaseq-samplesheet", str(rnaseq_path),
        "--tumor-sample", tumor_sample,
        "--normal-sample", normal_sample,
        "--sex", sex,
    ]
    if args.run_tag:
        argv += ["--run-tag", args.run_tag]
    for entry in args.resume_workflow:
        argv += ["--resume-workflow", entry]
    for flag, val in [
        ("--sarek-id", args.sarek_id),
        ("--hlatyping-id", args.hlatyping_id),
        ("--rnaseq-id", args.rnaseq_id),
        ("--vcf-expr-id", args.vcf_expr_id),
        ("--epitopeprediction-id", args.epitopeprediction_id),
        ("--purecn-id", args.purecn_id),
        ("--post-processing-id", args.post_processing_id),
    ]:
        if val is not None:
            argv += [flag, str(val)]

    # Replace sys.argv so run_flow.py's argparse sees the right args
    sys.argv = argv
    sys.path.insert(0, str(REPO_ROOT))

    from dotenv import load_dotenv
    load_dotenv()

    # Import and run directly (avoids a subprocess, shares the same process)
    import run_flow
    run_flow.main()


if __name__ == "__main__":
    main()
