"""Tests for SeqeraClient — all HTTP calls mocked with respx."""
import json
import pytest
import respx
import httpx

from seqera_client import SeqeraClient

WS = "ws123"
BASE = "https://api.cloud.seqera.io"
CLIENT = SeqeraClient(token="fake", workspace_id=WS, api_url=BASE)


# ---------------------------------------------------------------------------
# Dataset API
# ---------------------------------------------------------------------------

@respx.mock
def test_create_dataset_success():
    respx.post(f"{BASE}/workspaces/{WS}/datasets").mock(
        return_value=httpx.Response(200, json={"dataset": {"id": "ds-abc"}})
    )
    ds_id = CLIENT.create_dataset("my-sheet")
    assert ds_id == "ds-abc"


@respx.mock
def test_create_dataset_409_returns_existing():
    """409 conflict → look up existing dataset by name and return its ID."""
    respx.post(f"{BASE}/workspaces/{WS}/datasets").mock(
        return_value=httpx.Response(409, json={})
    )
    respx.get(f"{BASE}/workspaces/{WS}/datasets").mock(
        return_value=httpx.Response(200, json={
            "datasets": [{"name": "my-sheet", "id": "ds-existing"}]
        })
    )
    ds_id = CLIENT.create_dataset("my-sheet")
    assert ds_id == "ds-existing"


# ---------------------------------------------------------------------------
# launch_pipeline — fresh start
# ---------------------------------------------------------------------------

@respx.mock
def test_launch_pipeline_fresh():
    pipeline_id = 99
    # GET /pipelines/{id}/launch
    respx.get(f"{BASE}/pipelines/{pipeline_id}/launch").mock(
        return_value=httpx.Response(200, json={
            "launch": {
                "id": "launch-pl-001",
                "pipeline": "https://github.com/nf-core/sarek",
                "revision": "3.5.1",
                "configText": "",
            }
        })
    )
    # POST /workflow/launch
    launch_route = respx.post(f"{BASE}/workflow/launch").mock(
        return_value=httpx.Response(200, json={"workflowId": "wf-123"})
    )

    wf_id = CLIENT.launch_pipeline(
        pipeline_id=pipeline_id,
        compute_env_id="ce-abc",
        work_dir="s3://bucket/work",
        params={"genome": "GRCh38", "outdir": "s3://bucket/out"},
        run_name="test-run-001",
    )

    assert wf_id == "wf-123"
    body = json.loads(launch_route.calls[0].request.content)["launch"]
    assert body["resume"] is False
    assert body["runName"] == "test-run-001"
    assert body["revision"] == "3.5.1"
    assert json.loads(body["paramsText"])["genome"] == "GRCh38"


@respx.mock
def test_launch_pipeline_fresh_no_inherited_profiles():
    """configProfiles from launchpad template must NOT be inherited."""
    pipeline_id = 99
    respx.get(f"{BASE}/pipelines/{pipeline_id}/launch").mock(
        return_value=httpx.Response(200, json={
            "launch": {
                "id": "lp-001",
                "pipeline": "https://github.com/nf-core/rnaseq",
                "revision": "main",
                "configText": "",
                "configProfiles": ["test"],   # launchpad has 'test' profile
            }
        })
    )
    launch_route = respx.post(f"{BASE}/workflow/launch").mock(
        return_value=httpx.Response(200, json={"workflowId": "wf-456"})
    )

    CLIENT.launch_pipeline(
        pipeline_id=pipeline_id,
        compute_env_id="ce-abc",
        work_dir="s3://bucket/work",
        params={},
        run_name="test-run",
    )

    body = json.loads(launch_route.calls[0].request.content)["launch"]
    assert body["configProfiles"] == []  # test profile must be stripped


@respx.mock
def test_launch_pipeline_resume():
    """Resume path: uses workflow entity launchId and sets resume=true + sessionId."""
    pipeline_id = 99
    prev_wf_id = "old-wf-abc"

    respx.get(f"{BASE}/pipelines/{pipeline_id}/launch").mock(
        return_value=httpx.Response(200, json={
            "launch": {
                "id": "lp-pipeline",
                "pipeline": "https://github.com/nf-core/sarek",
                "revision": "3.5.1",
                "configText": "",
            }
        })
    )
    respx.get(f"{BASE}/workflow/{prev_wf_id}/launch").mock(
        return_value=httpx.Response(200, json={
            "launch": {
                "id": "lp-workflow",          # workflow-entity launchId
                "sessionId": "sess-xyz",
            }
        })
    )
    launch_route = respx.post(f"{BASE}/workflow/launch").mock(
        return_value=httpx.Response(200, json={"workflowId": "wf-new"})
    )

    wf_id = CLIENT.launch_pipeline(
        pipeline_id=pipeline_id,
        compute_env_id="ce-abc",
        work_dir="s3://bucket/work",
        params={},
        run_name="should-be-ignored",
        resume_from_workflow_id=prev_wf_id,
    )

    assert wf_id == "wf-new"
    body = json.loads(launch_route.calls[0].request.content)["launch"]
    assert body["resume"] is True
    assert body["id"] == "lp-workflow"      # must use workflow-entity launchId
    assert body["sessionId"] == "sess-xyz"
    assert "runName" not in body            # runName omitted on resume


# ---------------------------------------------------------------------------
# poll_until_complete
# ---------------------------------------------------------------------------

@respx.mock
def test_poll_succeeds_immediately():
    wf_id = "wf-done"
    respx.get(f"{BASE}/workflow/{wf_id}").mock(
        return_value=httpx.Response(200, json={
            "workflow": {"status": "SUCCEEDED", "exitStatus": "0"}
        })
    )
    status = CLIENT.poll_until_complete(wf_id, poll_interval=0)
    assert status == "SUCCEEDED"


@respx.mock
def test_poll_raises_on_failure():
    wf_id = "wf-fail"
    respx.get(f"{BASE}/workflow/{wf_id}").mock(
        return_value=httpx.Response(200, json={
            "workflow": {"status": "FAILED", "exitStatus": "1"}
        })
    )
    with pytest.raises(RuntimeError, match="FAILED"):
        CLIENT.poll_until_complete(wf_id, poll_interval=0)


@respx.mock
def test_poll_tolerates_transient_errors(monkeypatch):
    """Up to max_consecutive_errors-1 API failures should not raise."""
    wf_id = "wf-flaky"
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ConnectError("timeout")
        return httpx.Response(200, json={
            "workflow": {"status": "SUCCEEDED", "exitStatus": "0"}
        })

    respx.get(f"{BASE}/workflow/{wf_id}").mock(side_effect=side_effect)
    status = CLIENT.poll_until_complete(wf_id, poll_interval=0, max_consecutive_errors=5)
    assert status == "SUCCEEDED"
    assert call_count == 3
