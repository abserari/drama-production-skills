import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
state=load('state',ROOT/'skills/comfy-h3-video-producer/scripts/production_state.py')
imp=load('migration',ROOT/'scripts/import_legacy_project.py')
def test_atomic_failed_write_preserves_previous(tmp_path):
 p=tmp_path/'progress.json'; state.atomic_json(p,{'status':'passed'})
 with pytest.raises(ValueError): state.atomic_json(p,{'bad':float('nan')})
 assert state.read_json(p)=={'status':'passed'}
def test_corrupt_state_fails_closed(tmp_path):
 p=tmp_path/'progress.json'; p.write_text('{')
 with pytest.raises(json.JSONDecodeError): state.read_json(p,{})
def test_changed_artifact_invalidates_review(tmp_path):
 p=tmp_path/'v'; p.write_bytes(b'old'); old=state.file_hash(p); p.write_bytes(b'new')
 with pytest.raises(ValueError): state.require_artifact(p,old)
def test_actual_dialogue_changes_fingerprint():
 assert state.fingerprint({'dialogue':'a'}) != state.fingerprint({'dialogue':'b'})
def test_import_conflict_and_idempotence(tmp_path):
 src=tmp_path/'source'; prod=src/'生产'; prod.mkdir(parents=True)
 (src/'plan.json').write_text(json.dumps({'segs':[{'seg':'a'}]}))
 (prod/'plan.json').write_text(json.dumps({'segs':[{'seg':'b'}]}))
 assert imp.import_project(src,tmp_path/'blocked')['status']=='blocked'
 assert not (tmp_path/'blocked/project.json').exists()
 (prod/'plan.json').write_bytes((src/'plan.json').read_bytes())
 first=imp.import_project(src,tmp_path/'imported')
 assert imp.import_project(src,tmp_path/'imported')==first
 assert first['status']=='imported_unverified'
