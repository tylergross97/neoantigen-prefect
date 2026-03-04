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

    token: str = field(default_factory=lambda: os.environ["TOWER_ACCESS_TOKEN"])
    api_url: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_API_URL", "https://api.cloud.seqera.io"
        )
    )
    workspace_id: str = field(
        default_factory=lambda: os.getenv("SEQERA_WORKSPACE_ID", "242762077936819")
    )
    compute_env_id: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_COMPUTE_ENV_ID", "2uTyYrtzkHWBJwd6wFsK8I"
        )
    )
    work_dir: str = field(
        default_factory=lambda: os.getenv(
            "SEQERA_WORK_DIR",
            "s3://1000g-data-link-test-eu-west-1-iwcyt6phg/work",
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
            "s3://1000g-data-link-test-eu-west-1-iwcyt6phg/neoantigen",
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
    sarek: int | None = 63782075010441              # nf-core/sarek

    # Step 2 — HLA class I typing (WES reads)
    hlatyping: int | None = 80345911577300          # nf-core/hlatyping

    # Step 3 — RNA-seq quantification
    rnaseq: int | None = 62172493141868             # nf-core/rnaseq

    # Step 4 — annotate VCF with gene/transcript expression
    vcf_expression_annotator: int | None = 66496502716200   # vcf-expression-annotator

    # Step 5 — MHC-I:peptide binding prediction
    epitopeprediction: int | None = 166495825050255  # nf-core/epitopeprediction

    # Step 6 — tumor purity / clonality estimation (parallel to steps 3-5)
    purecn: int | None = 86054682767651             # nextflow-purecn

    # Steps 7+8 — downstream merge + tertiary prioritisation (single pipeline)
    post_processing: int | None = 227282378461823   # post-processing

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

def sarek_vep_vcf(outdir: str, sample: str) -> str:
    """VEP-annotated VCF produced by nf-core/sarek."""
    return f"{outdir}/annotation/{sample}/vep/{sample}.ann.vcf.gz"


def sarek_cnvkit_cns(outdir: str, sample: str) -> str:
    return f"{outdir}/cnvkit/{sample}.cns"


def sarek_cnvkit_cnr(outdir: str, sample: str) -> str:
    return f"{outdir}/cnvkit/{sample}.cnr"


def hlatyping_result(outdir: str, sample: str) -> str:
    """HLA-I allele result file from nf-core/hlatyping."""
    return f"{outdir}/hlatyping/{sample}_result.tsv"


def rnaseq_salmon_dir(outdir: str) -> str:
    """star_salmon output directory from nf-core/rnaseq."""
    return f"{outdir}/star_salmon"


def vcf_expr_annotated_vcf(outdir: str) -> str:
    """Expression-annotated VCF (VCF format) from vcf-expression-annotator."""
    return f"{outdir}/output.vcf.gz"


def vcf_expr_annotated_csv(outdir: str) -> str:
    """Expression-annotated VCF (CSV format) from vcf-expression-annotator."""
    return f"{outdir}/output.csv"


def epitopeprediction_results(outdir: str) -> str:
    """Binding prediction results directory from nf-core/epitopeprediction."""
    return f"{outdir}/pipeline_results"


def epitopeprediction_tsv(outdir: str, sample: str) -> str:
    """Merged binding predictions TSV from nf-core/epitopeprediction.
    Adjust filename if your epitopeprediction version uses a different convention."""
    return f"{outdir}/pipeline_results/{sample}_predictions.tsv"


def purecn_variants_csv(outdir: str, sample: str) -> str:
    """Per-variant CCF table (CSV) from nextflow-purecn."""
    return f"{outdir}/{sample}_variants.csv"
