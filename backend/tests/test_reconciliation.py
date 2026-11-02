"""Phase 4 comparison, evidence boundaries and reviewed mutations (isolated DBs)."""
from datetime import datetime, timedelta, timezone
import json
import time

import pytest

from app.models import AppService, ContainerGroup, ContainerGroupAssignment, ContainerGroupOverride, Hardware, VM, db
from app.services.discovery_identity import discovery_metadata
from app.services.group_identity import app_identity
from app.services.group_resolution import effective_group

HEADERS = {"X-Admin-Token": "reconciliation-test-only"}


@pytest.fixture()
def inventory(app):
    betty = Hardware(name="Betty", ip_address="192.0.2.10", hostname="betty.example")
    blackbox = Hardware(name="Blackbox", ip_address="192.0.2.20")
    db.session.add_all([betty, blackbox]); db.session.flush()
    docker = VM(name="Docker", hardware_id=betty.id, ip_address="192.0.2.10")
    remote = VM(name="Docker", hardware_id=blackbox.id)
    db.session.add_all([docker, remote]); db.session.flush()
    plex = AppService(name="Media Server", vm_id=docker.id,
                      notes="User notes  \n## Docker configuration\nContainer: plex\nContainer ID: old-container\nImage ID: old-image\nImage: plex:old\n")
    friendly = AppService(name="Friendly UI", vm_id=docker.id, port=443, icon="★", description="My custom description",
                          notes="Keep all my notes and whitespace.  \n\n")
    other = AppService(name="Regular service", hardware_id=betty.id)
    foreign = AppService(name="Remote Plex", vm_id=remote.id, port=443, description="Docker container: plex")
    group = ContainerGroup(name="Manual choice", source="manual", host_key="betty")
    imported = ContainerGroup(name="Tools", source="folderview", host_key="betty", external_id="tools")
    db.session.add_all([plex, friendly, other, foreign, group, imported]); db.session.flush()
    db.session.add(ContainerGroupOverride(group_id=group.id, host_key="betty", container_key="friendly ui"))
    for key in ["open-webui", "missing-tool"]:
        db.session.add(ContainerGroupAssignment(group_id=imported.id, host_key="betty", container_key=key))
    db.session.commit()
    app.config["ADMIN_TOKEN"] = "reconciliation-test-only"
    return {"host": betty, "other_host": blackbox, "plex": plex, "friendly": friendly,
            "foreign": foreign, "group": group, "imported": imported}


def snapshot(containers=None, **changes):
    data = {"schema_version": 1, "host_key": "Betty", "source": "separate test collector", "status": "success",
            "complete": True, "coverage": "all_containers", "completed_at": datetime.now(timezone.utc).isoformat(),
            "containers": containers if containers is not None else [{"container_name": "plex", "container_id": "new-container", "image_id": "new-image", "image": "plex:new"}]}
    data.update(changes)
    return data


def compare(client, payload=None, host="betty"):
    response = client.post('/api/reconciliation/compare', json={"host_key": host, "snapshot": payload})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def preview(client, payload, kind, key="plex", app_id=None):
    return client.post('/api/reconciliation/preview', json={"host_key": "betty", "snapshot": payload,
                      "action": {"kind": kind, "container_key": key, "app_id": app_id}})


def apply(client, response, headers=HEADERS):
    assert response.status_code == 200, response.get_json()
    return client.post('/api/reconciliation/apply', json={"token": response.get_json()["token"]}, headers=headers)


def test_no_scan_means_unknown_and_grouping_gaps_are_investigation_targets(inventory, client):
    before = AppService.query.count()
    report = compare(client)
    assert report['scan']['status'] == 'missing'
    assert all(row['classification'] == 'unknown' for row in report['inventory'])
    assert {row['container_key'] for row in report['folderview_unmatched']} == {'open-webui', 'missing-tool'}
    assert len(report['ungrouped']) == 2
    assert AppService.query.count() == before
    assert client.get('/api/reconciliation?host_key=betty').status_code == 200


def test_stable_identity_and_changed_ids_do_not_create_duplicates(inventory, client):
    report = compare(client, snapshot())
    row = report['containers'][0]
    assert row['classification'] == 'matched'
    assert row['app_id'] == inventory['plex'].id
    assert {f['field'] for f in row['changes']} == {'container_id', 'image_id', 'image'}
    assert inventory['foreign'].id not in row['candidate_ids']
    assert inventory['plex'].notes.startswith('User notes')


def test_complete_empty_scan_marks_only_recorded_docker_apps_absent_without_deleting(inventory, client):
    report = compare(client, snapshot([]))
    assert report['scan']['authoritative'] is True
    absent = [r['app_id'] for r in report['inventory'] if r['classification'] == 'confirmed_absent']
    assert absent == [inventory['plex'].id]
    assert AppService.query.count() == 4


@pytest.mark.parametrize('changes', [
    {'status': 'failed'}, {'complete': False}, {'coverage': 'running_only'},
    {'completed_at': None}, {'completed_at': 'invalid'}, {'completed_at': '2020-01-01T00:00:00'},
    {'completed_at': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()},
    {'completed_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()},
])
def test_failed_partial_old_and_missing_data_never_prove_absence(inventory, client, changes):
    report = compare(client, snapshot([], **changes))
    assert report['scan']['authoritative'] is False
    assert not any(r['classification'] == 'confirmed_absent' for r in report['inventory'])
    assert AppService.query.count() == 4


def test_missing_container_array_cannot_be_interpreted_as_empty_complete_scan(inventory, client):
    data = snapshot(); del data['containers']
    assert client.post('/api/reconciliation/compare', json={'host_key': 'betty', 'snapshot': data}).status_code == 400


def test_docker_inspect_subset_is_normalised_and_secret_fields_are_discarded(inventory, client):
    data = snapshot([{'Name': '/PLEX', 'Id': 'recreated', 'Image': 'sha256:changed',
                      'Config': {'Image': 'plex:new', 'Env': ['PASSWORD=do-not-retain']}, 'Mounts': ['private-path']}])
    report = compare(client, data)
    assert report['containers'][0]['app_id'] == inventory['plex'].id
    assert 'do-not-retain' not in json.dumps(report)
    assert 'private-path' not in json.dumps(report)
    response = apply(client, preview(client, data, 'update', app_id=inventory['plex'].id))
    assert response.status_code == 200
    assert 'do-not-retain' not in inventory['plex'].notes
    assert discovery_metadata(inventory['plex'].notes)['container_id'] == 'recreated'


def test_duplicate_inventory_and_discovery_identities_block_changes(inventory, client):
    db.session.add(AppService(name='PLEX', hardware_id=inventory['host'].id)); db.session.commit()
    report = compare(client, snapshot())
    assert report['containers'][0]['classification'] == 'duplicate'
    assert len(report['duplicates'][0]['inventory_ids']) == 2
    assert preview(client, snapshot(), 'update', app_id=inventory['plex'].id).status_code == 400
    report = compare(client, snapshot([{'container_name': 'new'}, {'container_name': 'NEW'}]))
    assert next(row for row in report['duplicates'] if row['container_key'] == 'new')['discovered_count'] == 2
    assert preview(client, snapshot([{'container_name': 'new'}, {'container_name': 'NEW'}]), 'add', key='new').status_code == 400


def test_duplicate_root_host_names_are_not_silently_combined(inventory, client):
    db.session.add(Hardware(name=' BETTY ')); db.session.commit()
    assert client.post('/api/reconciliation/compare', json={'host_key': 'betty'}).status_code == 400


def test_preview_addition_is_read_only_then_explicit_apply_adds_once(inventory, client):
    payload = snapshot([{'container_name': 'new-tool'}])
    reviewed = preview(client, payload, 'add', key='new-tool')
    assert reviewed.status_code == 200
    assert AppService.query.count() == 4
    assert {'name', 'parent host', 'logical identity'} <= {f['field'] for f in reviewed.get_json()['plan']['fields']}
    result = apply(client, reviewed)
    assert result.status_code == 200
    added = db.session.get(AppService, result.get_json()['app_id'])
    assert app_identity(added)[0:3:2] == ('betty', 'new-tool')
    assert added.hostname == 'betty.example'
    assert apply(client, reviewed).status_code == 409  # Replay cannot create another record.
    assert AppService.query.count() == 5


def test_preview_update_preserves_parent_id_name_and_existing_notes(inventory, client):
    app = inventory['plex']; original_notes = app.notes
    graph_before = client.get('/api/map/graph').get_json()
    parent = app.vm_id
    reviewed = preview(client, snapshot(), 'update', app_id=app.id)
    assert discovery_metadata(app.notes) == {}
    assert apply(client, reviewed).status_code == 200
    assert app.name == 'Media Server' and app.vm_id == parent
    assert app.notes.startswith(original_notes)
    assert discovery_metadata(app.notes)['image_id'] == 'new-image'
    assert client.get('/api/map/graph').get_json() == graph_before
    reviewed = preview(client, snapshot([{'container_name': 'plex'}]), 'update', app_id=app.id)
    assert apply(client, reviewed).status_code == 200
    assert discovery_metadata(app.notes)['image_id'] == 'new-image'  # Missing observation does not clear known metadata.


def test_manual_match_keeps_app_id_notes_and_manual_override(inventory, client):
    app = inventory['friendly']; original = app.notes; parent = app.vm_id
    assignments = [a.to_dict() for a in ContainerGroupAssignment.query.all()]
    data = snapshot([{'container_name': 'open-webui', 'container_id': 'runtime-id'}])
    reviewed = preview(client, data, 'match', key='open-webui', app_id=app.id)
    fields = reviewed.get_json()['plan']['fields']
    assert any(f['field'] == 'manual group override' and f['after'] == 'Manual choice for open-webui' for f in fields)
    assert apply(client, reviewed).status_code == 200
    assert app.name == 'Friendly UI' and app.vm_id == parent and app.icon == '★'
    assert app.notes.startswith(original)
    assert app_identity(app)[2] == 'open-webui'
    assert effective_group(db.session, 'betty', 'open-webui').id == inventory['group'].id
    assert [a.to_dict() for a in ContainerGroupAssignment.query.all()] == assignments
    assert ContainerGroupOverride.query.filter_by(container_key='friendly ui').count() == 0
    backup = client.get('/inventory/export').get_json()
    assert any(discovery_metadata(row['notes']).get('container_name') == 'open-webui' for row in backup['apps'])


def test_explicit_ungrouped_override_survives_manual_matching(inventory, client):
    override = ContainerGroupOverride.query.one(); override.group_id = None; db.session.commit()
    response = preview(client, snapshot([{'container_name': 'open-webui'}]), 'match', key='open-webui', app_id=inventory['friendly'].id)
    assert apply(client, response).status_code == 200
    assert ContainerGroupOverride.query.one().container_key == 'open-webui'
    assert ContainerGroupOverride.query.one().group_id is None
    assert effective_group(db.session, 'betty', 'open-webui') is None


def test_conflicting_overrides_and_other_host_matching_are_rejected(inventory, client):
    data = snapshot([{'container_name': 'open-webui'}])
    assert preview(client, data, 'match', key='open-webui', app_id=inventory['foreign'].id).status_code == 400
    db.session.add(ContainerGroupOverride(host_key='betty', container_key='open-webui', group_id=None)); db.session.commit()
    assert preview(client, data, 'match', key='open-webui', app_id=inventory['friendly'].id).status_code == 400


def test_cannot_bind_two_present_resources_to_one_application(inventory, client):
    data = snapshot([{'container_name': 'plex'}, {'container_name': 'open-webui'}])
    assert preview(client, data, 'match', key='open-webui', app_id=inventory['plex'].id).status_code == 400


@pytest.mark.parametrize('change_group', [False, True])
def test_concurrent_inventory_or_group_changes_invalidate_previews(inventory, client, change_group):
    reviewed = preview(client, snapshot(), 'update', app_id=inventory['plex'].id)
    if change_group:
        inventory['group'].active = False
    else:
        inventory['plex'].notes += '\nA concurrent edit.'
    db.session.commit()
    assert apply(client, reviewed).status_code == 409
    assert discovery_metadata(inventory['plex'].notes) == {}


def test_writes_require_admin_and_unsigned_or_expired_previews_are_rejected(inventory, client, app, monkeypatch):
    reviewed = preview(client, snapshot(), 'update', app_id=inventory['plex'].id)
    assert apply(client, reviewed, {}).status_code == 401
    app.config['ADMIN_TOKEN'] = ''
    assert apply(client, reviewed).status_code == 503
    app.config['ADMIN_TOKEN'] = 'reconciliation-test-only'
    assert client.post('/api/reconciliation/apply', json={'token': 'forged'}, headers=HEADERS).status_code == 409
    actual = time.time
    with monkeypatch.context() as m:
        m.setattr('itsdangerous.timed.time.time', lambda: actual() - 700)
        old = preview(client, snapshot(), 'update', app_id=inventory['plex'].id)
    assert apply(client, old).status_code == 409
    assert AppService.query.count() == 4


def test_failed_scan_cannot_produce_a_write_preview(inventory, client):
    assert preview(client, snapshot(status='failed'), 'update', app_id=inventory['plex'].id).status_code == 400


def test_upstream_portscan_is_read_only_endpoint_evidence_not_container_evidence(inventory, client):
    report = compare(client, {'data': {'scan_id': 'fixture', 'type': 'portscan', 'status': 'completed', 'progress': 100,
                                     'params': {'target_ip': '192.0.2.10', 'port_range': '1-1024'},
                                     'results': [{'port': 443, 'service_name': 'https', 'http_probe': {'suggested_name': 'UI', 'error': None}}],
                                     'complete': True, 'coverage': 'all_containers', 'completed_at': datetime.now(timezone.utc).isoformat()}})
    assert report['scan']['containers'] == [] and report['scan']['authoritative'] is False
    row = report['network']['rows'][0]
    assert row['classification'] == 'matched'
    assert row['matches'] == [{'id': inventory['friendly'].id, 'name': 'Friendly UI', 'type': 'apps'}]
    assert all(r['classification'] == 'unknown' for r in report['inventory'])


@pytest.mark.parametrize('status', ['failed', 'running', 'expired'])
def test_failed_running_expired_network_jobs_never_mark_containers_stale(inventory, client, status):
    state = {'scan_id': 'fixture', 'status': status, 'results': [], 'params': {}}
    if status != 'expired':
        state['type'] = 'discover'
    report = compare(client, {'data': state})
    assert report['network']['status'] == status
    assert not report['scan']['authoritative']
    assert not any(r['classification'] == 'confirmed_absent' for r in report['inventory'])


def test_upstream_host_identification_and_probe_failure_are_compared_safely(inventory, client):
    report = compare(client, {'data': {'scan_id': 'fixture', 'type': 'identify', 'status': 'completed',
                                     'params': {'target_ip': '192.0.2.10'},
                                     'results': [{'hostname': 'betty.example', 'mac_address': None, 'os': 'Unraid'}]}})
    assert report['network']['rows'][0]['matches'][0]['id'] == inventory['host'].id
    report = compare(client, {'data': {'scan_id': 'fixture', 'type': 'probe_http', 'status': 'completed',
                                     'params': {'target_ip': '192.0.2.10', 'port': 443},
                                     'results': [{'error': 'do-not-echo-private-error', 'suggested_name': None}]}})
    assert report['network']['rows'][0]['classification'] == 'unverified'
    assert 'do-not-echo-private-error' not in json.dumps(report)


def test_older_snapshot_cannot_regress_known_metadata_or_claim_current_absence(inventory, client):
    app = inventory['plex']
    assert apply(client, preview(client, snapshot(), 'update', app_id=app.id)).status_code == 200
    older = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    data = snapshot(completed_at=older)
    report = compare(client, data)
    assert report['containers'][0]['classification'] == 'older_observation'
    assert preview(client, data, 'update', app_id=app.id).status_code == 400
    absent = compare(client, snapshot([], completed_at=older))
    row = next(r for r in absent['inventory'] if r['app_id'] == app.id)
    assert row['classification'] == 'unknown'
    assert 'newer recorded observation' in row['reason']
    assert discovery_metadata(app.notes)['image_id'] == 'new-image'


def test_generated_metadata_is_backup_compatible_and_cannot_escape_its_html_comment(inventory, client):
    app = inventory['plex']
    original_notes = app.notes
    payload = snapshot([{'container_name': 'plex', 'image': 'text --><img src=x>'}])
    assert apply(client, preview(client, payload, 'update', app_id=app.id)).status_code == 200
    assert app.notes.startswith(original_notes)
    assert '<img' not in app.notes
    assert discovery_metadata(app.notes)['image'] == 'text --><img src=x>'
    backup = client.get('/inventory/export').get_json()
    assert client.post('/inventory/import', json=backup).status_code == 200
    restored = AppService.query.filter_by(name='Media Server').one()
    assert app_identity(restored)[2] == 'plex'
    assert discovery_metadata(restored.notes)['image'] == 'text --><img src=x>'


def test_blackbox_docker_in_vm_uses_its_root_host_and_vm_service_endpoint(inventory, client):
    foreign = inventory['foreign']
    foreign.vm.ip_address = '192.0.2.30'; db.session.commit()
    report = compare(client, snapshot(host_key='Blackbox'), host='blackbox')
    assert report['containers'][0]['app_id'] == foreign.id
    assert all(a['id'] != inventory['plex'].id for a in report['applications'])
    report = compare(client, {'data': {'scan_id': 'fixture', 'type': 'portscan', 'status': 'completed',
                                     'params': {'target_ip': '192.0.2.30'}, 'results': [{'port': 443}]}}, host='blackbox')
    assert report['network']['rows'][0]['matches'][0]['id'] == foreign.id


def test_invalid_names_and_schema_do_not_silently_change_logical_identity(inventory, client):
    for name in ['bad name', 'a' * 129, '', None]:
        data = snapshot([{'container_name': name}])
        assert client.post('/api/reconciliation/compare', json={'host_key': 'betty', 'snapshot': data}).status_code == 400
    assert client.post('/api/reconciliation/compare', json={'host_key': 'betty', 'snapshot': snapshot(schema_version=True)}).status_code == 400
    assert AppService.query.count() == 4


def test_missing_vm_address_does_not_guess_service_endpoint_from_physical_host(inventory, client):
    inventory['friendly'].vm.ip_address = None; db.session.commit()
    report = compare(client, {'data': {'scan_id': 'fixture', 'type': 'portscan', 'status': 'completed',
                                     'params': {'target_ip': '192.0.2.10'}, 'results': [{'port': 443}]}})
    assert report['network']['rows'][0]['classification'] == 'unmatched'
    assert report['network']['rows'][0]['matches'] == []


def test_apply_failure_rolls_back_both_metadata_and_override_identity(inventory, client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.routes import reconciliation as routes
    app = inventory['friendly']; before = app.notes
    reviewed = preview(client, snapshot([{'container_name': 'open-webui'}]), 'match', key='open-webui', app_id=app.id)
    execute = routes.execute_action
    def fail_after_flush(plan):
        execute(plan)
        raise OperationalError('simulated storage failure', {}, Exception('fixture failure'))
    monkeypatch.setattr(routes, 'execute_action', fail_after_flush)
    assert apply(client, reviewed).status_code == 409
    assert app.notes == before
    assert ContainerGroupOverride.query.one().container_key == 'friendly ui'
    assert effective_group(db.session, 'betty', 'friendly ui').id == inventory['group'].id
