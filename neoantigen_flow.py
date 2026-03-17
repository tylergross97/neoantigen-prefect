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
    "intervals": "s3://1000g-data-link-test-eu-west-1-iwcyt6phg/neoantigen/references/Exome-Agilent_V5.bed",
    "trim_fastq": True,
    "vep_genome": "GRCh38",
    "vep_species": "homo_sapiens",
    "vep_cache_version": 110,
    "vep_dbnsfp": False,
    "vep_loftee": False,
    "save_reference": False,
    "skip_tools": "baserecalibrator_report",
    "validate_params": False,           # suppress param schema errors for validationLenientMode
    "validationLenientMode": True,      # warn instead of error on .FASTQ.gz uppercase extension
}

HLATYPING_PARAMS: dict = {
    "genome": "hg38",
    "solver": "glpk",               # LP solver for OptiType
    # "seqtype" was removed in nf-core/hlatyping v2.x (invalid param in v2.2.0)
    "validate_params": False,       # suppress param schema errors for validationLenientMode
    "validationLenientMode": True,  # warn instead of error on .FASTQ.gz uppercase extension
}

RNASEQ_PARAMS: dict = {
    # GENCODE GRCh38 annotation produces ENST* transcript IDs that match VEP's
    # Ensembl annotation in the sarek VCF. The "GRCh38" genome key uses the NCBI
    # iGenomes STAR index which assigns internal rna0/rna1 IDs → 0% expression matches.
    "fasta": "s3://ngi-igenomes/igenomes/Homo_sapiens/NCBI/GRCh38/Sequence/WholeGenomeFasta/genome.fa",
    "gtf": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_44/gencode.v44.primary_assembly.annotation.gtf.gz",
    "save_reference": True,         # saves Salmon index + transcript FASTA for reuse across patients
    "pseudo_aligner": "salmon",     # quasi-mapping mode; skips STAR alignment entirely
    "skip_alignment": True,         # skip STAR index build + alignment (~2h + $1.57/patient saved)
    "skip_markduplicates": True,    # not applicable in pseudo-alignment mode
    "skip_qc": True,                # qualimap, dupradar, rseqc not needed ($0.67 saved)
    "skip_bigwig": True,            # bigwig files not used downstream
    "skip_stringtie": True,         # stringtie output not used downstream
    "save_unaligned": False,
    "deseq2_vst": False,            # DESeq2 VST not needed; we use raw salmon counts
    "validate_params": False,       # suppress param schema errors for validationLenientMode
    "validationLenientMode": True,  # warn instead of error on .FASTQ.gz uppercase extension
}

EPITOPEPREDICTION_PARAMS: dict = {
    "tools": "mhcflurry,mhcnuggets",
    "genome_reference": "GRCh38",
    "min_peptide_length_classI": 8,
    "max_peptide_length_classI": 11,
    "wild_type": True,              # also predict WT peptides for binding delta
    # mhc_class and alleles go in the per-sample samplesheet, not as pipeline params
}

PURECN_PARAMS: dict = {
    # snp_blacklist is set at launch time to an S3 path (HTTP URLs fail Nextflow's .exists() check)
    # fasta/gtf removed: PureCN.R uses --genome hg38, not --fasta/--gtf flags
}

_PURECN_SNP_BLACKLIST_URL = "https://raw.githubusercontent.com/tylergross97/nextflow_purecn/refs/heads/main/tests/data/hg38_encode_blacklist.bed"

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
    rnaseq_transcript_counts_tsv,
    sarek_cnvkit_cnr,
    sarek_cnvkit_cns,
    sarek_mutect2_filtered_vcf,
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
    normal_sample_name: str               # used to build sarek vs-name output paths
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
    normal = inputs.normal_sample_name

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
        # Do NOT use `set -u` — the pre-run script is sourced by nf-launcher.sh
        # and `-u` would cause it to fail on unbound vars like TOWER_CONFIG_BASE64.
        # Use a plain string (no textwrap.dedent) so indentation is exact.
        return (
            "aws s3 cp - '" + s3_path + "' << 'SAMPLESHEET_EOF'\n"
            + safe.rstrip("\n") + "\n"
            + "SAMPLESHEET_EOF\n"
        )

    ss_base = f"{seqera_cfg.base_outdir}/{pid}/samplesheets"
    wes_s3          = f"{ss_base}/wes.csv"
    hla_s3          = f"{ss_base}/hlatyping.csv"
    rnaseq_s3       = f"{ss_base}/rnaseq.csv"
    vcf_expr_ss_s3  = f"{ss_base}/vcf_expression_annotator.csv"
    purecn_ss_s3    = f"{ss_base}/purecn.csv"
    epipred_ss_s3   = f"{ss_base}/epitopeprediction.csv"
    purecn_blacklist_s3 = f"{seqera_cfg.base_outdir}/references/hg38_encode_blacklist.bed"

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
        revision="3.5.1",   # 3.4.4 has Channel.empty([[]]) bug with NF 25.10.4

        launch_delay_seconds=0,
    )

    # Step 2 — nf-core/hlatyping: HLA class I typing from normal WES reads
    hlatyping_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.hlatyping,
        pipeline_name="hlatyping",
        run_tag=tag,
        params={
            **HLATYPING_PARAMS,
            "input": hla_s3,
            "outdir": outdir("hlatyping"),
        },
        pre_run_script=_upload_script(inputs.hlatyping_samplesheet_csv, hla_s3),
        revision="2.2.0",
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

    # patient_id strips the "{pid}_" prefix from rnaseq sample names when
    # splitting salmon.merged.transcript_counts.tsv into per-sample files.
    # e.g. "PID262622_T" → strip "PID262622_" → sample_id "T"
    vcf_expr_patient_id = f"{pid}_"
    vcf_expr_short_id = sample[len(pid) + 1:]  # e.g. "T"
    vcf_expr_ss_csv = (
        "sample_id,vcf_path,vcf_tumor_sample\n"
        f"{vcf_expr_short_id},"
        f"{sarek_vep_vcf(outdir('sarek'), sample, normal)},"
        f"{pid}_{sample}"
    )

    vcf_annot_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.vcf_expression_annotator,
        pipeline_name="vcf-expression-annotator",
        run_tag=tag,
        params={
            "patient_id": vcf_expr_patient_id,
            "samplesheet": vcf_expr_ss_s3,
            "transcript_counts": rnaseq_transcript_counts_tsv(outdir("rnaseq")),
            "outdir": outdir("vcf_expression_annotator"),
        },
        pre_run_script=_upload_script(vcf_expr_ss_csv, vcf_expr_ss_s3),

        wait_for=[sarek_future, rnaseq_future],
    )

    # ── Step 6: PureCN (waits for sarek only) ──────────────────────────────
    # Runs in parallel with steps 4 and 5.

    purecn_ss_csv = (
        "sample_id,tumor_cns,tumor_cnr,vcf\n"
        f"{sample},"
        f"{sarek_cnvkit_cns(outdir('sarek'), sample, normal)},"
        f"{sarek_cnvkit_cnr(outdir('sarek'), sample, normal)},"
        f"{sarek_mutect2_filtered_vcf(outdir('sarek'), sample, normal)}"
    )

    purecn_pre_run = (
        _upload_script(purecn_ss_csv, purecn_ss_s3)
        + f"\ncurl -sL '{_PURECN_SNP_BLACKLIST_URL}' | aws s3 cp - '{purecn_blacklist_s3}'"
    )

    purecn_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.purecn,
        pipeline_name="PureCN",
        run_tag=tag,
        params={
            **PURECN_PARAMS,
            "snp_blacklist": purecn_blacklist_s3,
            "samplesheet": purecn_ss_s3,
            "outdir_base": outdir("purecn"),
        },
        pre_run_script=purecn_pre_run,
        revision="stable-hg38",

        wait_for=[sarek_future],
    )

    # ── Step 5: nf-core/epitopeprediction (waits for vcf_annot + hlatyping) ─
    # Depends on: step 4 (expression-annotated VCF), step 2 (HLA alleles)
    #
    # epitopeprediction --input is a samplesheet CSV (sample,alleles,mhc_class,filename).
    # alleles and mhc_class are per-sample samplesheet columns, not pipeline params.
    # The pre-run script:
    #   1. Downloads the hlatyping result TSV from S3
    #   2. Strips the HLA- prefix and joins alleles with ";"
    #   3. Uploads the epitopeprediction samplesheet to S3

    hlatyping_s3 = hlatyping_result(outdir("hlatyping"), normal)
    vcf_for_epipred = vcf_expr_annotated_vcf(
        outdir("vcf_expression_annotator"), vcf_expr_patient_id, vcf_expr_short_id
    )
    epipred_pre_run = (
        f"HLATYPING_S3='{hlatyping_s3}'\n"
        f"EPIPRED_SS_S3='{epipred_ss_s3}'\n"
        f"VCF_S3='{vcf_for_epipred}'\n"
        f"SAMPLE_ID='{sample}'\n"
        "\n"
        # Download hlatyping result and extract alleles (strip HLA- prefix, join with ;)
        # OptiType TSV: row 0 = header, row 1 = data; cols 2-7 are A1,A2,B1,B2,C1,C2
        "ALLELES=$(aws s3 cp \"$HLATYPING_S3\" - | "
        "awk 'NR==2{gsub(/HLA-/,\"\"); printf \"%s;%s;%s;%s;%s;%s\\n\",$2,$3,$4,$5,$6,$7}')\n"
        # Write and upload the samplesheet
        "printf 'sample,alleles,mhc_class,filename\\n%s,%s,I,%s\\n' "
        "\"$SAMPLE_ID\" \"$ALLELES\" \"$VCF_S3\" | aws s3 cp - \"$EPIPRED_SS_S3\"\n"
    )

    epipred_future = run_pipeline.submit(
        cfg=seqera_cfg,
        pipeline_id=pipeline_ids.epitopeprediction,
        pipeline_name="nf-core/epitopeprediction",
        run_tag=tag,
        params={
            **EPITOPEPREDICTION_PARAMS,
            "input": epipred_ss_s3,
            "outdir": outdir("epitopeprediction"),
        },
        pre_run_script=epipred_pre_run,

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
        f"{vcf_expr_annotated_csv(outdir('vcf_expression_annotator'), vcf_expr_patient_id, vcf_expr_short_id)},"
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
