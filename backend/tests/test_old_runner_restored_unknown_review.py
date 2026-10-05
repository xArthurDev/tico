"""Legacy human restore remains compatible after an offline/unknown transition."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.test_worktrees import api, gh, prepared, post, auth  # noqa: F401
from backend.tests.test_worktree_old_runner_residual_review import heartbeat


@pytest.mark.parametrize(("saved_state", "report_state"), [("present", "missing"), ("unknown", "present")])
def test_pre_upgrade_old_restore_receipt_has_no_new_marker(prepared, saved_state, report_state):
    api, tid, _ = prepared
    link = post(api, f"tasks/{tid}/worktrees", {"repo": "Acme/product"}).json()
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with api.app_state.store.transaction() as c:
        c.execute("UPDATE task_links SET state=?,detail_json=? WHERE id=?", (
            saved_state, json.dumps({"owner": "bot:cmo", "setup_pending": True, "missing_since": old}), link["link_id"]))
    for _ in range(3):
        assert heartbeat(api, link, report_state) == []
        with api.app_state.store.read() as c:
            row = c.execute("SELECT state,detail_json FROM task_links WHERE id=?", (link["link_id"],)).fetchone()
            detail = json.loads(row["detail_json"])
            assert row["state"] == report_state
            assert detail["setup_pending"] is True
            assert detail.get("checkout_state") is None
            assert not any(detail.get(k) for k in ("expected_head", "checkout_target", "expected_base"))
    with api.app_state.store.read() as c:
        wakes = c.execute("SELECT count(*) FROM messages WHERE body LIKE 'Worktree missing for a day:%'").fetchone()[0]
        assert wakes == (1 if report_state == "missing" else 0)


def test_old_human_restore_recovers_unknown_without_demoting_or_inventing_proof(prepared):
    api, tid, _ = prepared
    link = post(api, f"tasks/{tid}/worktrees", {"repo": "Acme/product"}).json()
    assert heartbeat(api, link)[0]["action"] == "restore"
    response = api.patch(f'/api/v2/tasks/{tid}/links/{link["link_id"]}',
                         json={"state": "present", "setup_pending": True},
                         headers={**auth("runner-test"), "Idempotency-Key": uuid.uuid4().hex})
    assert response.status_code == 200, response.text
    # The server marks known trees unknown when worktree capability is temporarily absent.
    response = post(api, "runners/heartbeat", {
        "version": "0.2.35", "platform": "darwin",
        "readiness": {"schema_version": 1, "worktrees": False}, "worktrees": [],
    }, "runner-test")
    assert response.status_code == 200, response.text
    with api.app_state.store.read() as c:
        assert c.execute("SELECT state FROM task_links WHERE id=?", (link["link_id"],)).fetchone()[0] == "unknown"
    for _ in range(3):
        assert heartbeat(api, link, "present") == []
        with api.app_state.store.read() as c:
            row = c.execute("SELECT state,detail_json FROM task_links WHERE id=?", (link["link_id"],)).fetchone()
            detail = json.loads(row["detail_json"])
            assert row["state"] == "present"
            assert detail["setup_pending"] is True
            assert detail.get("checkout_state") is None
            assert not any(detail.get(k) for k in ("expected_head", "checkout_target", "expected_base"))
