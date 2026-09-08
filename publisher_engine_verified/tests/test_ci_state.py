import gzip
from pathlib import Path
import pytest
from leadengine.db import Database
from scripts import ci_state as s

def test_state_round_trip_retains_quota(tmp_path):
    source=tmp_path/'source.db';db=Database(source)
    assert db.reserve('tavily',17,700,'month')
    db.add_site('https://honista.com/','test');target=tmp_path/'target.db'
    s.unpack_database(s.packed_database(source),target);restored=Database(target)
    assert restored.rows('SELECT units FROM usage')[0]['units']==17
    assert restored.rows('SELECT domain FROM sites')[0]['domain']=='honista.com'
def test_corrupt_state_preserves_existing_file(tmp_path):
    path=tmp_path/'state.db';Database(path);before=path.read_bytes()
    with pytest.raises(RuntimeError):s.unpack_database(gzip.compress(b'not sqlite'),path)
    assert path.read_bytes()==before

def test_missing_state_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'file_meta',lambda p:None)
    def missing(*a,**kw):raise s.ApiError(404)
    monkeypatch.setattr(s,'api',missing)
    with pytest.raises(RuntimeError,match='State missing'):s.restore_state('repos/a/b',tmp_path/'db',tmp_path/'marker',False)
    assert not (tmp_path/'db').exists()
def test_existing_branch_missing_database_not_reset(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'file_meta',lambda p:None);monkeypatch.setattr(s,'api',lambda *a,**kw:{'ref':'state'})
    with pytest.raises(RuntimeError,match='State missing'):s.restore_state('repos/a/b',tmp_path/'db',tmp_path/'marker',True)
def test_save_needs_successful_restore(tmp_path):
    with pytest.raises(RuntimeError,match='Restore was not successful'):s.save_state('repos/a/b',tmp_path/'db',tmp_path/'marker')
def test_public_repo_refused(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY','owner/repo');monkeypatch.setattr(s,'api',lambda *a,**kw:{'private':False})
    with pytest.raises(RuntimeError,match='non-private'):s.repo_prefix()
def test_no_network_errors_treated_as_fresh_state(monkeypatch):
    def forbidden(*a,**kw):raise s.ApiError(403)
    monkeypatch.setattr(s,'api',forbidden)
    with pytest.raises(s.ApiError):s.file_meta('repos/a/b')
def test_workflow_private_guard_and_secrets_not_in_upload():
    import yaml
    f=Path(__file__).parents[1]/'.github/workflows/publisher-leads.yml';w=yaml.safe_load(f.read_text())
    assert w['on']['schedule'][0]['timezone']=='Asia/Jerusalem'
    assert 'private' in w['jobs']['discover']['if']
    assert w['jobs']['discover']['timeout-minutes']==20
    upload=w['jobs']['discover']['steps'][-1]['with']['path']
    assert '.env' not in upload and 'data/exports/' in upload
