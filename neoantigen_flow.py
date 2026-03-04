"""
Prefect flow: end-to-end neoantigen prediction pipeline.

DAG (matches the Mermaid diagram):

  wes_fastq ──────────────── sarek (1) ────── VEP VCF ─────────────────────────────────────────────┐
                           │                  CNS/CNR ─── purecn (6) ─── CCF CSV ────────────────┐  │
                           └──────────────── hlatyping (2) ─── HLA alleles ─────────────────────┐│  │
  rnaseq_fastq ─────────── rnaseq (3) ─── expression ─────────────────────────────────────────┐ ││  │
                                                                                               ↓ ↓↓  ↓
                                                          vcf-expression-annotator (4) ← vep_vcf + expr
                                                                     │
                                                                     ├─ annotated VCF ─── epitopeprediction (5) ← HLA alleles
                                                                     └─ CSV format ────────────────────────┐
                                                                                                           ↓
                                                                                         post-processing (7+8)
                                                                                         ← binding TSV + CCF CSV
                                                                                                           │
                                                                                                           ↓
                                                                                           Prioritized Neoantigens
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# Fixed pipeline parameters
# All non-dynamic params live here so the launchpad entries need zero defaults.
# Update these when upgrading pipeline versions or changing analysis settings.
# ---------------------------------------------------------------------------

SAREK_PARAMS: dict = {
    "genome": "GATK.GRCh38",
    "tools": "mutect2,vep,cnvkit",
    "wes": True,                    # WES mode (adjusts CNV normalisation)
    "trim_fastq": True,
    "vep_genome": "GRCh38",
    "vep_species": "homo_sapiens",
    "vep_cache_version": 110,
    "vep_dbnsfp": False,
    "vep_loftee": False,
    "save_reference": False,
    "skip_tools": "baserecalibrator_report",
}

HLATYPING_PARAMS: dict = {
    "genome": "hg38",
    "solver": "glpk",               # LP solver for OptiType
    "seqtype": "dna",               # use DNA reads (not rna)
}

RNASEQ_PARAMS: dict = {
    "genome": "GRCh38",
    "aligner": "star_salmon",
    "pseudo_aligner": "salmon",
    "pseudo_aligner_kmer_size": 31,
    "skip_markduplicates": False,
    "skip_qc": False,
    "save_unaligned": False,
    "deseq2_vst": True,
}

EPITOPEPREDICTION_PARAMS: dict = {
    "mhc_class": "I",
    "tools": "syfpeithi,mhcflurry,mhcnuggets",
    "min_peptide_length": 8,
    "max_peptide_length": 11,
    "genome": "GRCh38",
    "proteome": "homo_sapiens",
    "wild_type": True,              # also predict WT peptides for binding delta
}

PURECN_PARAMS: dict = {
    "genome": "hg38",
    "assay": "WES",
    "fun_segmentation": "PSCBS",
    "extra_commands": "--min-purity 0.1 --max-purity 1.0",
}

# ---------------------------------------------------------------------------

import textwrap

from prefect import flow, get_run_logger

import config as cfg_module
from config import (
    PipelineIds,
    SeqeraConfig,
    epitopeprediction_results,
    epitopeprediction_tsv,
    hlatyping_result,
    purecn_variants_csv,
    rnaseq_salmon_dir,
    sarek_cnvkit_cnr,
    sarek_cnvkit_cns,
    sarek_vep_vcf,
    vcf_expr_annotated_csv,
    vcf_expr_annotated_vcf,
)
from tasks import create_and_upload_dataset, run_pipeline


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class NeoantigenInputs:
    """
    All inputs needed to run the neoantigen pipeline for a single patient.

    wes_samplesheet_csv  — CSV text of the WES samplesheet (sarek + hlatyping format).
                           nf-core/sarek expects: patient,sample,lane,fastq_1,fastq_2,bam,...
    rnaseq_samplesheet_csv — CSV text for nf-core/rnaseq: sample,fastq_1,fastq_2,strandedness
    tumor_sample_name    — Sample name as it appears in the sarek samplesheet (used to
                           build output paths like {sample}.ann.vcf.gz).
    """

    patient_id: str
    wes_samplesheet_csv: str
    hlatyping_samplesheet_csv: str        # sample,fastq_1,fastq_2,seq_type (normal reads only)
    rnaseq_samplesheet_csv: str
    tumor_sample_name: str
    sex: str = "XX"                       # XX or XY — used in sarek WES samplesheet
    run_tag: str = field(default="")      # optional, defaults to patient_id + date

    def __post_init__(self) -> None:
        if not self.run_tag:
            ts = datetime.utcnow().strftime("%Y%m%d-%H%M")
            self.run_tag = f"{self.patient_id}-{ts}"


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------

@flow(
    name="neoantigen-prediction",
    description="8-step neoantigen prediction pipeline orchestrated via Seqera Platform",
    log_prints=True,
)
def neoantigen_flow(
    inputs: NeoantigenInputs,
    seqera_cfg: SeqeraConfig | None = None,
    pipeline_ids: PipelineIds | None = None,
) -> str:
    """
    Run the full neoantigen prediction DAG for a single patient.

    Returns the S3 path of the post-processing output directory.
    """
    logger = get_run_logger()

    seqera_cfg = seqera_cfg or SeqeraConfig()
    pipeline_ids = pipeline_ids or PipelineIds()
    pipeline_ids.validate()  # fail fast if any IDs are still None

    pid = inputs.patient_id
    tag = inputs.run_tag
    sample = inputs.tumor_sample_name

    def outdir(step: str) -> str:
        return seqera_cfg.outdir(pid, step)

    def _upload_script(csv_content: str, s3_path: str) -> str:
        """
        Return a bash pre-run script that writes csv_content to s3_path.

        Runs on the Seqera Compute head node (which has AWS credentials) before
        Nextflow starts. Using a single-quoted heredoc prevents any shell
        expansion of the CSV content.
        """
        # Escape any occurrence of the sentinel in the content (shouldn't happen)
        safe = csv_content.replace("SAMPLESHEET_EOF", "SAMPLESHEET_EO_F")
        return textwrap.dedent(f"""\
            #!/bin/bash
            set -euo pipefail
            aws s3 cp - '{s3_path}' << 'SAMPLESHEET_EOF'
            {safe}SAMPLESHEET_EOF
        """)

    ss_base = f"{seqera_cfg.base_outdir}/{pid}/samplesheets"
    wes_s3      = f"{ss_base}/wes.csv"
    hla_s3      = f"{ss_base}/hlatyping.csv"
    rnaseq_s3   = f"{ss_base}/rnaseq.csv"

    logger.info(f"Starting neoantigen pipeline for patient={pid}, tag={tag}")

    # ── Steps 1, 2, 3: Parallel launch ─────────────────────────────────────
    # Samplesheets are written to S3 via pre-run scripts (bash heredocs that
    # run on the compute head node before Nextflow starts). This avoids the
    # nf-schema ^\S+\.csv$ validation failure that occurs with dataset:// or
    # Seqera API HTTPS URLs.

    # Step 1 — nf-core/sarek: somatic variant calling
    # Steps 1-3 are staggered by 5s to avoid Seqera API concurrency errors
    # when multiple launches hit the same compute environment simultaneously.
    # Pre-run scripts upload the samplesheet CSV to S3 before Nextflow starts,
    # so --input can be a plain S3 path that passes nf-schema validation.
    sarek_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.sarek,
        pipeline_name="nf-core/sarek",
        run_tag=tag,
        params={
            **SAREK_PARAMS,
            "input": wes_s3,
            "outdir": outdir("sarek"),
        },
        pre_run_script=_upload_script(inputs.wes_samplesheet_csv, wes_s3),
        launch_delay_seconds=0,
    )

    # Step 2 — nf-core/hlatyping: HLA class I typing from normal WES reads
    hlatyping_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.hlatyping,
        pipeline_name="nf-core/hlatyping",
        run_tag=tag,
        params={
            **HLATYPING_PARAMS,
            "input": hla_s3,
            "outdir": outdir("hlatyping"),
        },
        pre_run_script=_upload_script(inputs.hlatyping_samplesheet_csv, hla_s3),
        launch_delay_seconds=5,
    )

    # Step 3 — nf-core/rnaseq: transcript-level quantification
    rnaseq_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.rnaseq,
        pipeline_name="nf-core/rnaseq",
        run_tag=tag,
        params={
            **RNASEQ_PARAMS,
            "input": rnaseq_s3,
            "outdir": outdir("rnaseq"),
        },
        pre_run_script=_upload_script(inputs.rnaseq_samplesheet_csv, rnaseq_s3),
        launch_delay_seconds=10,
    )

    # ── Step 4: vcf-expression-annotator (waits for sarek + rnaseq) ────────
    # Depends on: step 1 (VEP VCF), step 3 (salmon expression)
    # Runs in parallel with step 6 (PureCN) after sarek finishes.

    vcf_annot_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.vcf_expression_annotator,
        pipeline_name="vcf-expression-annotator",
        run_tag=tag,
        params={
            "vcf": sarek_vep_vcf(outdir("sarek"), sample),
            "expression_dir": rnaseq_salmon_dir(outdir("rnaseq")),
            "outdir": outdir("vcf_expression_annotator"),
            "sample": sample,
        },
        wait_for=[sarek_future, rnaseq_future],
    )

    # ── Step 6: PureCN (waits for sarek only) ──────────────────────────────
    # Runs in parallel with steps 4 and 5.

    purecn_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.purecn,
        pipeline_name="PureCN",
        run_tag=tag,
        params={
            **PURECN_PARAMS,
            "vcf": sarek_vep_vcf(outdir("sarek"), sample),
            "cns": sarek_cnvkit_cns(outdir("sarek"), sample),
            "cnr": sarek_cnvkit_cnr(outdir("sarek"), sample),
            "outdir": outdir("purecn"),
            "sample": sample,
        },
        wait_for=[sarek_future],
    )

    # ── Step 5: nf-core/epitopeprediction (waits for vcf_annot + hlatyping) ─
    # Depends on: step 4 (expression-annotated VCF), step 2 (HLA alleles)

    epipred_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.epitopeprediction,
        pipeline_name="nf-core/epitopeprediction",
        run_tag=tag,
        params={
            **EPITOPEPREDICTION_PARAMS,
            "input": vcf_expr_annotated_vcf(outdir("vcf_expression_annotator")),
            "alleles": hlatyping_result(outdir("hlatyping"), sample),
            "outdir": outdir("epitopeprediction"),
        },
        wait_for=[vcf_annot_future, hlatyping_future],
    )

    # ── Steps 7+8: post-processing (waits for epipred + vcf_annot + purecn) ─
    # Builds a per-patient samplesheet and uploads it as a Seqera Dataset,
    # then runs the post-processing pipeline which executes both:
    #   - neoantigen_downstream (merge binding predictions + expression CSV)
    #   - tertiary (join with PureCN CCF estimates and prioritise)

    # Resolve all upstream futures before building the samplesheet
    epipred_future.result()
    vcf_annot_future.result()
    purecn_future.result()

    pp_samplesheet_csv = (
        "sample_id,variants_expression,binding_predictions,purecn_path\n"
        f"{sample},"
        f"{vcf_expr_annotated_csv(outdir('vcf_expression_annotator'))},"
        f"{epitopeprediction_tsv(outdir('epitopeprediction'), sample)},"
        f"{purecn_variants_csv(outdir('purecn'), sample)}"
    )

    pp_dataset_future = create_and_upload_dataset.submit(
        cfg=seqera_cfg,
        name=f"{pid}-post-processing-input-{tag}",
        csv_content=pp_samplesheet_csv,
    )
    pp_dataset_uri = pp_dataset_future.result()

    post_processing_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.post_processing,
        pipeline_name="post-processing",
        run_tag=tag,
        params={
            "input": pp_dataset_uri,
            "outdir": outdir("post_processing"),
        },
    )

    post_processing_future.result()  # block until the flow is truly complete

    final_outdir = outdir("post_processing")
    logger.info(
        f"Neoantigen pipeline COMPLETE for patient {pid}\n"
        f"  Results: {final_outdir}"
    )
    return final_outdir
