"""Tests for task utilities and flow parameter assembly."""
import re
import pytest
from unittest.mock import MagicMock, patch, call
from tasks import _safe_run_name
from neoantigen_flow import NeoantigenInputs, SAREK_PARAMS, RNASEQ_PARAMS, HLATYPING_PARAMS


# ---------------------------------------------------------------------------
# _safe_run_name
# ---------------------------------------------------------------------------

SEQERA_RUN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,38}[a-z0-9]$")


def test_safe_run_name_basic():
    name = _safe_run_name("nf-core/sarek", "PID001-20260101-1200")
    assert SEQERA_RUN_NAME_RE.match(name), f"Invalid run name: {name!r}"


def test_safe_run_name_strips_slashes():
    name = _safe_run_name("nf-core/sarek", "tag")
    assert "/" not in name


def test_safe_run_name_max_length():
    name = _safe_run_name("nf-core/sarek", "a" * 50)
    assert len(name) <= 40


def test_safe_run_name_no_consecutive_hyphens():
    name = _safe_run_name("nf-core/sarek", "PID001-20260101-1200")
    assert "--" not in name


def test_safe_run_name_no_leading_trailing_hyphens():
    name = _safe_run_name("nf-core/sarek", "tag")
    assert not name.startswith("-")
    assert not name.endswith("-")


# ---------------------------------------------------------------------------
# NeoantigenInputs — run_tag auto-generation
# ---------------------------------------------------------------------------

def test_neoantigen_inputs_auto_run_tag():
    inputs = NeoantigenInputs(
        patient_id="PID001",
        wes_samplesheet_csv="a,b",
        hlatyping_samplesheet_csv="c,d",
        rnaseq_samplesheet_csv="e,f",
        tumor_sample_name="PID001_T",
        normal_sample_name="PID001_N",
    )
    assert inputs.run_tag.startswith("PID001-")
    assert len(inputs.run_tag) > len("PID001-")


def test_neoantigen_inputs_explicit_run_tag():
    inputs = NeoantigenInputs(
        patient_id="PID001",
        wes_samplesheet_csv="a",
        hlatyping_samplesheet_csv="b",
        rnaseq_samplesheet_csv="c",
        tumor_sample_name="PID001_T",
        normal_sample_name="PID001_N",
        run_tag="my-custom-tag",
    )
    assert inputs.run_tag == "my-custom-tag"


# ---------------------------------------------------------------------------
# Fixed pipeline parameter dicts — spot-check critical values
# ---------------------------------------------------------------------------

def test_sarek_params_has_required_tools():
    assert "mutect2" in SAREK_PARAMS["tools"]
    assert "vep" in SAREK_PARAMS["tools"]
    assert "cnvkit" in SAREK_PARAMS["tools"]


def test_sarek_params_wes_mode():
    assert SAREK_PARAMS["wes"] is True


def test_rnaseq_params_uses_gencode_gtf():
    """GENCODE GTF is required for ENST* transcript IDs that match VEP output."""
    assert "gencode" in RNASEQ_PARAMS["gtf"].lower()


def test_rnaseq_params_no_genome_key():
    """Must NOT use iGenomes 'genome' key — that gives internal rna0/rna1 IDs."""
    assert "genome" not in RNASEQ_PARAMS


def test_rnaseq_params_saves_reference():
    """save_reference must be True so Salmon index is reused across patients."""
    assert RNASEQ_PARAMS["save_reference"] is True


def test_rnaseq_params_pseudo_alignment_mode():
    """Must use pseudo-alignment with STAR skipped."""
    assert RNASEQ_PARAMS["pseudo_aligner"] == "salmon"
    assert RNASEQ_PARAMS["skip_alignment"] is True
    assert "aligner" not in RNASEQ_PARAMS


def test_hlatyping_no_seqtype_param():
    """seq_type was removed in nf-core/hlatyping v2.x — must not be set."""
    assert "seqtype" not in HLATYPING_PARAMS
    assert "seq_type" not in HLATYPING_PARAMS


# ---------------------------------------------------------------------------
# Upload script format (heredoc generation)
# ---------------------------------------------------------------------------

def test_upload_script_format():
    """
    The pre-run heredoc script must use single-quoted EOF (no shell expansion)
    and aws s3 cp - syntax.
    """
    from neoantigen_flow import NeoantigenInputs, neoantigen_flow
    from config import SeqeraConfig, PipelineIds

    captured = {}

    def fake_run_pipeline(cfg, pipeline_id, pipeline_name, run_tag, params,
                          pre_run_script=None, revision=None,
                          launch_delay_seconds=0, **kwargs):
        captured[pipeline_name] = pre_run_script
        return "fake-workflow-id"

    csv = "patient,sex,status,sample\nPID001,XX,1,PID001_T\n"

    with patch("neoantigen_flow.run_pipeline") as mock_task:
        # Make .submit() call the fake directly and return a mock future
        def submit_side_effect(*args, **kwargs):
            result = fake_run_pipeline(*args, **kwargs)
            future = MagicMock()
            future.result.return_value = result
            return future

        mock_task.submit.side_effect = submit_side_effect

        import os
        os.environ.setdefault("TOWER_ACCESS_TOKEN", "fake")

        inputs = NeoantigenInputs(
            patient_id="PID001",
            wes_samplesheet_csv=csv,
            hlatyping_samplesheet_csv="sample,fastq_1,fastq_2\n",
            rnaseq_samplesheet_csv="sample,fastq_1,fastq_2,strandedness\n",
            tumor_sample_name="PID001_T",
            normal_sample_name="PID001_N",
            run_tag="test-tag",
        )

        neoantigen_flow(
            inputs=inputs,
            seqera_cfg=SeqeraConfig(),
            pipeline_ids=PipelineIds(
                sarek=1, hlatyping=2, rnaseq=3,
                vcf_expression_annotator=4, epitopeprediction=5,
                purecn=6, post_processing=7,
            ),
        )

    sarek_script = captured.get("nf-core/sarek", "")
    # Must use aws s3 cp - (stdin) not aws s3 cp <file>
    assert "aws s3 cp -" in sarek_script
    # Must use single-quoted heredoc to prevent shell expansion
    assert "'SAMPLESHEET_EOF'" in sarek_script
    # CSV content must appear verbatim
    assert "PID001_T" in sarek_script
