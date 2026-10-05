"""Independent review regression for consecutive API-attachment heartbeats."""
import json

from runner import worktrees as W
from runner.tests.test_worktrees import git, trees  # noqa: F401


def test_api_attachment_stays_ready_across_consecutive_heartbeats(trees):
    workspace, base, remote, row, client = trees
    path = workspace / row['path']
    path.parent.mkdir(parents=True)
    git(base, 'worktree', 'add', '--no-track', '-b', row['branch'], str(path), 'origin/main')
    row.update(state='pending', detail_json=json.dumps({
        'checkout_state': 'attached_pending', 'setup_pending': False,
    }))

    first = W.inspect(workspace, row)
    assert first['state'] == 'present', first
    # Persist the same completion fields the cloud heartbeat stores.
    detail = json.loads(row['detail_json'])
    detail.update({key: value for key, value in first.items()
                   if key not in ('state', 'link_id', 'branch')})
    row.update(state=first['state'], detail_json=json.dumps(detail))

    second = W.inspect(workspace, row)
    assert second['state'] == 'present', second
    assert W._read_marker(workspace, row['id'])['phase'] == 'ready'
    assert (path / 'file').read_text() == 'initial'
