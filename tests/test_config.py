"""Tests for config.py path helpers and dataclasses."""
import pytest
from config import (
    PipelineIds,
    SeqeraConfig,
    epitopeprediction_tsv,
    hlatyping_result,
    purecn_variants_csv,
    rnaseq_transcript_counts_tsv,
    sarek_cnvkit_cnr,
    sarek_cnvkit_cns,
    sarek_mutect2_filtered_vcf,
    sarek_vep_vcf,
    vcf_expr_annotated_csv,
    vcf_expr_annotated_vcf,
)

OUTDIR = "s3://bucket/neoantigen/PID001"
TUMOR = "PID001_T"
NORMAL = "PID001_N"
VS = f"{TUMOR}_vs_{NORMAL}"


# ---------------------------------------------------------------------------
# sarek output paths
# ---------------------------------------------------------------------------

def test_sarek_vep_vcf():
    path = sarek_vep_vcf(OUTDIR, TUMOR, NORMAL)
    assert path == f"{OUTDIR}/annotation/mutect2/{VS}/{VS}.mutect2.filtered_VEP.ann.vcf.gz"


def test_sarek_mutect2_filtered_vcf():
    path = sarek_mutect2_filtered_vcf(OUTDIR, TUMOR, NORMAL)
    assert path == f"{OUTDIR}/variant_calling/mutect2/{VS}/{VS}.mutect2.filtered.vcf.gz"


def test_sarek_cnvkit_cns():
    path = sarek_cnvkit_cns(OUTDIR, TUMOR, NORMAL)
    assert path == f"{OUTDIR}/variant_calling/cnvkit/{VS}/{TUMOR}.cns"


def test_sarek_cnvkit_cnr():
    path = sarek_cnvkit_cnr(OUTDIR, TUMOR, NORMAL)
    assert path == f"{OUTDIR}/variant_calling/cnvkit/{VS}/{TUMOR}.cnr"


# ---------------------------------------------------------------------------
# hlatyping / rnaseq output paths
# ---------------------------------------------------------------------------

def test_hlatyping_result():
    path = hlatyping_result(OUTDIR, "PID001_N")
    assert path == f"{OUTDIR}/hlatyping/PID001_N_result.tsv"


def test_rnaseq_transcript_counts_tsv():
    path = rnaseq_transcript_counts_tsv(OUTDIR)
    assert path == f"{OUTDIR}/salmon/salmon.merged.transcript_counts.tsv"


# ---------------------------------------------------------------------------
# vcf-expression-annotator output paths
# ---------------------------------------------------------------------------

def test_vcf_expr_annotated_vcf():
    path = vcf_expr_annotated_vcf(OUTDIR, "PID001_", "T")
    assert path == f"{OUTDIR}/vcf_expression_annotator/PID001_T.expression_vep.chr22.vcf.gz"


def test_vcf_expr_annotated_csv():
    path = vcf_expr_annotated_csv(OUTDIR, "PID001_", "T")
    assert path == f"{OUTDIR}/vcf_to_csv/PID001_T_neoantigen.csv"


# ---------------------------------------------------------------------------
# epitopeprediction / purecn output paths
# ---------------------------------------------------------------------------

def test_epitopeprediction_tsv():
    path = epitopeprediction_tsv(OUTDIR, "PID001_T")
    assert path == f"{OUTDIR}/predictions/PID001_T.tsv"


def test_purecn_variants_csv():
    path = purecn_variants_csv(OUTDIR, "PID001_T")
    assert path == f"{OUTDIR}/purecn/PID001_T_purecn_output/PID001_T_variants.csv"


# ---------------------------------------------------------------------------
# SeqeraConfig.outdir
# ---------------------------------------------------------------------------

def test_seqera_config_outdir(monkeypatch):
    monkeypatch.setenv("SEQERA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("SEQERA_BASE_OUTDIR", "s3://bucket/neoantigen")
    cfg = SeqeraConfig()
    assert cfg.outdir("PID001", "sarek") == "s3://bucket/neoantigen/PID001/sarek"
    assert cfg.outdir("PID001", "rnaseq") == "s3://bucket/neoantigen/PID001/rnaseq"


# ---------------------------------------------------------------------------
# PipelineIds.validate
# ---------------------------------------------------------------------------

def test_pipeline_ids_validate_passes():
    ids = PipelineIds(
        sarek=1, hlatyping=2, rnaseq=3,
        vcf_expression_annotator=4, epitopeprediction=5,
        purecn=6, post_processing=7,
    )
    ids.validate()  # should not raise


def test_pipeline_ids_validate_fails_on_none():
    ids = PipelineIds(sarek=None, hlatyping=2, rnaseq=3,
                     vcf_expression_annotator=4, epitopeprediction=5,
                     purecn=6, post_processing=7)
    with pytest.raises(ValueError, match="sarek"):
        ids.validate()


def test_pipeline_ids_validate_lists_all_missing():
    ids = PipelineIds(sarek=None, hlatyping=None, rnaseq=1,
                     vcf_expression_annotator=2, epitopeprediction=3,
                     purecn=4, post_processing=5)
    with pytest.raises(ValueError) as exc_info:
        ids.validate()
    msg = str(exc_info.value)
    assert "sarek" in msg
    assert "hlatyping" in msg
