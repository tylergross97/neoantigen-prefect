"""
Configuration for the neoantigen Prefect + Seqera Platform pipeline.

Pipeline IDs are set to None until the corresponding pipelines are added to the
Seqera launchpad. The flow validates all required IDs at startup.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class SeqeraConfig:
    """Seqera Platform workspace configuration."""

    token: str = field(default_factory=lambda: os.environ["SEQERA_ACCESS_TOKEN"])
    api_url: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_API_URL", "https://api.cloud.seqera.io"
        )
    )
    workspace_id: str = field(
        default_factory=lambda: os.getenv("SEQERA_WORKSPACE_ID", "241557511768949")
    )
    compute_env_id: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_COMPUTE_ENV_ID", "6iBrsUmU65TcxFFNv1fqdJ"
        )
    )
    work_dir: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_WORK_DIR",
            "s3://neoantigen-prefect-evjnnnoto/work",
        )
    )
    credentials_id: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_CREDENTIALS_ID", "33f9GRiZcRTdIa5beWm9u1"
        )
    )
    base_outdir: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_BASE_OUTDIR",
            "s3://neoantigen-prefect-evjnnnoto/neoantigen",
        )
    )

    def outdir(self, patient_id: str, step: str) -> str:
        return f"{self.base_outdir}/{patient_id}/{step}"


@dataclass
class PipelineIds:
    """
    Seqera Platform pipeline IDs (integer IDs from the launchpad URL).

    To find a pipeline ID: open the pipeline in Seqera Platform, the URL will
    contain /pipelines/{id}. Fill these in before running the flow.
    """

    # Step 1 — somatic variant calling (WES tumor+normal)
    sarek: int | None = 55964005363629              # nf-core/sarek

    # Step 2 — HLA class I typing (WES reads)
    hlatyping: int | None = 195834718545719         # nf-core/hlatyping

    # Step 3 — RNA-seq quantification
    rnaseq: int | None = 279916736539698            # nf-core/rnaseq

    # Step 4 — annotate VCF with gene/transcript expression
    vcf_expression_annotator: int | None = 115494822935647  # vcf-expression-annotator

    # Step 5 — MHC-I:peptide binding prediction
    epitopeprediction: int | None = 78969659774724  # nf-core/epitopeprediction

    # Step 6 — tumor purity / clonality estimation (parallel to steps 3-5)
    purecn: int | None = 109854476846005            # nextflow-purecn

    # Steps 7+8 — downstream merge + tertiary prioritisation (single pipeline)
    post_processing: int | None = 171371528787569   # post-processing

    def validate(self) -> None:
        """Raise ValueError listing any pipeline IDs that are still None."""
        missing = [
            name
            for name, val in self.__dict__.items()
            if val is None
        ]
        if missing:
            raise ValueError(
                f"Pipeline IDs not configured: {', '.join(missing)}\n"
                "Set them in config.py or pass a PipelineIds instance with real IDs."
            )


# ---------------------------------------------------------------------------
# Expected output path conventions (nf-core defaults)
# These are used to wire the output of one pipeline into the input of the next.
# Adjust if your pipeline configurations deviate from nf-core defaults.
# ---------------------------------------------------------------------------

def sarek_mutect2_filtered_vcf(outdir: str, tumor_sample: str, normal_sample: str) -> str:
    """Filtered (pre-VEP) Mutect2 VCF produced by nf-core/sarek.

    Published to: variant_calling/mutect2/{T}_vs_{N}/{T}_vs_{N}.mutect2.filtered.vcf.gz
    Used as PureCN --vcf input (somatic variant allele frequencies for CCF estimation).
    """
    vs = f"{tumor_sample}_vs_{normal_sample}"
    return f"{outdir}/variant_calling/mutect2/{vs}/{vs}.mutect2.filtered.vcf.gz"


def sarek_vep_vcf(outdir: str, tumor_sample: str, normal_sample: str) -> str:
    """VEP-annotated VCF produced by nf-core/sarek (somatic tumor-vs-normal).

    sarek v3.5.1 publishDir uses ${meta.variantcaller}/${meta.id}/ where
    meta.variantcaller='mutect2' (set in bam_variant_calling_somatic_mutect2).
    Path: annotation/mutect2/{tumor}_vs_{normal}/{tumor}_vs_{normal}.mutect2.filtered_VEP.ann.vcf.gz
    """
    vs = f"{tumor_sample}_vs_{normal_sample}"
    return f"{outdir}/annotation/mutect2/{vs}/{vs}.mutect2.filtered_VEP.ann.vcf.gz"


def sarek_cnvkit_cns(outdir: str, tumor_sample: str, normal_sample: str) -> str:
    """CNVkit .cns file published by nf-core/sarek v3.5.1.

    Published to: variant_calling/cnvkit/{tumor}_vs_{normal}/{tumor}.cns
    """
    vs = f"{tumor_sample}_vs_{normal_sample}"
    return f"{outdir}/variant_calling/cnvkit/{vs}/{tumor_sample}.cns"


def sarek_cnvkit_cnr(outdir: str, tumor_sample: str, normal_sample: str) -> str:
    """CNVkit .cnr file published by nf-core/sarek v3.5.1.

    Published to: variant_calling/cnvkit/{tumor}_vs_{normal}/{tumor}.cnr
    """
    vs = f"{tumor_sample}_vs_{normal_sample}"
    return f"{outdir}/variant_calling/cnvkit/{vs}/{tumor_sample}.cnr"


def hlatyping_result(outdir: str, sample: str) -> str:
    """HLA-I allele result file from nf-core/hlatyping.

    nf-core/hlatyping v2.x publishes to: optitype/{sample}/{sample}_result.tsv
    """
    return f"{outdir}/optitype/{sample}/{sample}_result.tsv"


def rnaseq_salmon_dir(outdir: str) -> str:
    """salmon output directory from nf-core/rnaseq (pseudo-alignment mode)."""
    return f"{outdir}/salmon"


def rnaseq_transcript_counts_tsv(outdir: str) -> str:
    """Merged transcript-level counts TSV from nf-core/rnaseq (pseudo-alignment mode)."""
    return f"{outdir}/salmon/salmon.merged.transcript_counts.tsv"


def vcf_expr_annotated_vcf(outdir: str, patient_id: str, sample_id: str) -> str:
    """Expression-annotated VCF from vcf-expression-annotator.

    Published to: {outdir}/vcf_expression_annotator/{patient_id}{sample_id}.expression_vep.chr22.vcf.gz
    Note: 'chr22' is hardcoded in the pipeline output filename regardless of input scope.
    """
    return f"{outdir}/vcf_expression_annotator/{patient_id}{sample_id}.expression_vep.chr22.vcf.gz"


def vcf_expr_annotated_csv(outdir: str, patient_id: str, sample_id: str) -> str:
    """Expression-annotated variants CSV from vcf-expression-annotator.

    Published to: {outdir}/vcf_to_csv/{patient_id}{sample_id}_neoantigen.csv
    """
    return f"{outdir}/vcf_to_csv/{patient_id}{sample_id}_neoantigen.csv"


def epitopeprediction_results(outdir: str) -> str:
    """Binding prediction results directory from nf-core/epitopeprediction."""
    return f"{outdir}/pipeline_results"


def epitopeprediction_tsv(outdir: str, sample: str) -> str:
    """Merged binding predictions TSV from nf-core/epitopeprediction.

    Published to: {outdir}/predictions/{sample}.tsv
    where {sample} is the 'sample' column in the epitopeprediction samplesheet
    (= tumor_sample_name, e.g. PID262622_T).
    """
    return f"{outdir}/predictions/{sample}.tsv"


def purecn_variants_csv(outdir: str, sample: str) -> str:
    """Per-variant CCF table (CSV) from nextflow-purecn.

    The pipeline sets outdir_purecn = {outdir_base}/purecn and publishes
    files with the --out prefix directly there (not in a subdirectory).
    Full path: {outdir}/purecn/{sample}_purecn_output_variants.csv
    """
    return f"{outdir}/purecn/{sample}_purecn_output_variants.csv"
