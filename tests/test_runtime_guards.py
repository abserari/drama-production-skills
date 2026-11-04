import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/comfy-h3-video-producer/scripts'
sys.path.insert(0,str(SCRIPTS))
import production_state as state
import h3proj
import sop_run

@pytest.fixture
def project(tmp_path,monkeypatch):
 monkeypatch.setattr(h3proj.paths,'COMFY',str(tmp_path))
 for key,val in {'PROJECT_DIR':str(tmp_path),'PROJECT_JSON':str(tmp_path/'project.json'),'PLAN':str(tmp_path/'plan.json'),'PROGRESS':str(tmp_path/'progress.json'),'FINISH_DIR':str(tmp_path/'finish')}.items():
  monkeypatch.setattr(h3proj.paths,key,val)
 state.atomic_json(tmp_path/'project.json',{'selected_skills':{'render':'v1'}})
 state.atomic_json(tmp_path/'plan.json',{'segs':[{'seg':'a','dialogue':False}]})
 video=tmp_path/'video.mp4';video.write_bytes(b'fixture-video-A')
 digest=state.file_hash(video)
 rec={'status':'完成','input_fingerprint':'generation-v1','input_snapshot':{'segment_spec':state.fingerprint(h3proj.seg_spec('a')),'production_context':state.render_context(h3proj.load_project()),'files':{}},'first':{'verdict':'PASS','video':str(video),'artifact_sha256':digest},'visual_review':{'verdict':'pass','artifact_sha256':digest},'deliver':{'verdict':'PASS','path':str(video),'artifact_sha256':digest,'input_fingerprint':'generation-v1'}}
 state.atomic_json(tmp_path/'progress.json',{'segs':{'a':rec}})
 return tmp_path,rec,video

def test_render_context_excludes_mixing_but_tracks_skill(project):
 base,rec,_=project
 state.atomic_json(base/'project.json',{'selected_skills':{'render':'v1'},'mixing':{'gain':0.1}})
 h3proj.require_current_inputs('a',rec)
 state.atomic_json(base/'project.json',{'selected_skills':{'render':'v2'}})
 with pytest.raises(SystemExit):h3proj.require_current_inputs('a',rec)

def test_changed_dialogue_blocks_old_result(project):
 base,rec,_=project
 state.atomic_json(base/'plan.json',{'segs':[{'seg':'a','dialogue':True,'text':'changed'}]})
 with pytest.raises(SystemExit):h3proj.require_current_inputs('a',rec)

def test_final_cannot_reuse_other_video_review(project):
 base,_,_=project; other=base/'other.mp4';other.write_bytes(b'video-B')
 with pytest.raises(SystemExit,match='final_review'):
  h3proj.cmd_finish(SimpleNamespace(seg='a',final=str(other)))

def test_concat_failure_preserves_old_output(project,monkeypatch):
 base,_,_=project;out=base/'film.mp4';out.write_bytes(b'old-good-film')
 monkeypatch.setattr(h3proj,'stream_summary',lambda p:{'width':320,'height':192,'duration':2,'has_video':True})
 monkeypatch.setattr(h3proj.paths,'tmp_audio',lambda:str(base))
 def failed(cmd,**kw):
  Path(cmd[-1]).write_bytes(b'broken-candidate');return SimpleNamespace(returncode=1,stderr='failure')
 monkeypatch.setattr(h3proj.subprocess,'run',failed)
 with pytest.raises(SystemExit):h3proj.cmd_concat(SimpleNamespace(order=None,out=str(out),audio_crossfade=0))
 assert out.read_bytes()==b'old-good-film'

def test_concat_rejects_input_alias(project):
 _,_,video=project
 with pytest.raises(SystemExit,match='输入分镜'):
  h3proj.cmd_concat(SimpleNamespace(order=None,out=str(video),audio_crossfade=0))

def test_blocking_review_needs_current_hash_and_human_source(tmp_path):
 media=tmp_path/'script.md';media.write_text('v1')
 plan={'required_reviews':[{'stage_id':'a','review_path':'review.json','artifact_path':'script.md','reviewer_kind':'human'}]}
 review={'status':'passed','reviewer_kind':'human','evidence':['user:turn-1'],'artifact_sha256':state.file_hash(media)}
 state.atomic_json(tmp_path/'review.json',review)
 with pytest.raises(ValueError,match='Human'):state.require_configured_reviews(tmp_path,plan,'a')
 review['human_source']='user:turn-1';state.atomic_json(tmp_path/'review.json',review)
 state.require_configured_reviews(tmp_path,plan,'a')
 media.write_text('v2')
 with pytest.raises(ValueError):state.require_configured_reviews(tmp_path,plan,'a')

def test_nonblocking_review_does_not_block(tmp_path):
 state.require_configured_reviews(tmp_path,{'required_reviews':[{'stage_id':'a','mode':'nonblocking'}]},'a')

def test_lost_receipt_reconciles_without_submission(project,monkeypatch):
 base,rec,_=project;rec.update(submission_state='unknown',submission_client_id='exact-client')
 state.atomic_json(base/'progress.json',{'segs':{'a':rec}})
 calls=[]
 def api(path,**kw):
  calls.append(path)
  return {'queue_running':[[0,'known-id',{}, {'client_id':'exact-client'}]],'queue_pending':[]} if path=='/queue' else {}
 monkeypatch.setattr(sop_run.paths,'http_json',api)
 sop_run.cmd_submit(SimpleNamespace(seg='a',dry_run=False))
 assert h3proj.load_progress()['segs']['a']['prompt_id']=='known-id'
 assert '/prompt' not in calls

def test_unresolved_receipt_refuses_even_force(project,monkeypatch):
 base,rec,_=project;rec.update(submission_state='unknown',submission_client_id='lost')
 state.atomic_json(base/'progress.json',{'segs':{'a':rec}})
 monkeypatch.setattr(sop_run.paths,'http_json',lambda *a,**k:{})
 with pytest.raises(SystemExit):sop_run.cmd_submit(SimpleNamespace(seg='a',dry_run=False,force=True))


def test_unconnected_or_wrong_first_frame_cannot_pass(tmp_path):
 a=tmp_path/'a.png';b=tmp_path/'b.png';a.write_bytes(b'frame-A');b.write_bytes(b'frame-B')
 graph={'cond':{'inputs':{'first_frame':['wrong',0]}},'wrong':{'class_type':'LoadImage','inputs':{'image':'b.png'}},'unused':{'class_type':'LoadImage','inputs':{'image':'a.png'}}}
 assert not state.connected_first_frame(graph,a,tmp_path)
 graph['cond']['inputs']['first_frame']=['unused',0]
 assert state.connected_first_frame(graph,a,tmp_path)


def test_audio_skill_change_does_not_invalidate_render():
 a={'selected_skills':{'render':'v1','drama-audio-soundstage':'v1'}}
 b={'selected_skills':{'render':'v1','drama-audio-soundstage':'v2'}}
 assert state.render_context(a)==state.render_context(b)


def test_os_gpu_lock_rejects_other_process_then_recovers(tmp_path):
 import subprocess
 key=str(tmp_path/'isolated-gpu')
 code="import sys;sys.path.insert(0,sys.argv[1]);from production_state import gpu_lock;\nwith gpu_lock(sys.argv[2]):print('acquired')"
 with state.gpu_lock(key):
  refused=subprocess.run([sys.executable,'-c',code,str(SCRIPTS),key],capture_output=True,text=True)
  assert refused.returncode != 0 and 'owned by another process' in refused.stderr
 recovered=subprocess.run([sys.executable,'-c',code,str(SCRIPTS),key],capture_output=True,text=True)
 assert recovered.returncode==0 and 'acquired' in recovered.stdout


def test_nested_project_compatibility_and_conflict():
 common={'production':{'route':'i2v','selected_skills':{'prompt':'v1'}}}
 normalized={'production':{'route':'i2v'},'selected_skills':{'prompt':'v1'}}
 assert state.render_context(common)==state.render_context(normalized)
 common['selected_skills']={'prompt':'v2'}
 with pytest.raises(ValueError,match='Conflicting'):state.render_context(common)


def test_skill_subdirectories_are_not_runtime_project_locations():
 assert h3proj.paths._inside_skill_tree(str(SCRIPTS/'temporary-project'))
 assert not h3proj.paths._inside_skill_tree(str(ROOT/'examples/project'))
 if sys.platform=='win32':assert not h3proj.paths._inside_skill_tree('D:/different-drive/project')

def test_keyframe_injection_does_not_overwrite_existing_node():
 spec=importlib.util.spec_from_file_location('kf_guard',ROOT/'skills/drama-keyframe-forge/scripts/keyframe_gate.py')
 kf=importlib.util.module_from_spec(spec);spec.loader.exec_module(kf)
 graph={'6':{'class_type':'MiniMaxH3ImageToVideo','inputs':{}},'20':{'class_type':'VAELoader','inputs':{'vae_name':'keep-me'}}}
 before=json.dumps(graph,sort_keys=True)
 with pytest.raises(ValueError,match='occupied'):kf.apply_keyframe_to_graph(graph,keyframe_filename='frame.png')
 assert json.dumps(graph,sort_keys=True)==before


def test_abort_never_clears_foreign_queue(monkeypatch):
 calls=[]
 def api(path,payload=None,**kw):
  calls.append((path,payload))
  return {'queue_running':[[0,'mine',{},{}]],'queue_pending':[[1,'other',{},{}]]} if path=='/queue' and payload is None else {}
 monkeypatch.setattr(sop_run.paths,'http_json',api)
 monkeypatch.setattr(sop_run.gpu_vram,'free',lambda **kw:pytest.fail('must not free while other work is queued'))
 sop_run._kill_queue('mine')
 assert ('/interrupt',{'prompt_id':'mine'}) in calls
 assert not any(payload and payload.get('clear') for _,payload in calls)
 assert not any(payload and 'other' in payload.get('delete',[]) for _,payload in calls)
 with pytest.raises(SystemExit):sop_run._kill_queue(None)


def test_workflow_drift_check_is_read_only(monkeypatch):
 import types
 calls=[]
 fake=types.SimpleNamespace(refresh_if_stale=lambda **kw:(calls.append(kw) or {'changed':True}))
 monkeypatch.setitem(sys.modules,'h3wf',fake)
 with pytest.raises(SystemExit,match='工作流源文件已修改'):sop_run._check_fresh(False)
 assert calls==[{'apply':False,'verbose':False}]


def test_asr_missing_local_model_does_not_download(tmp_path,monkeypatch):
 spec=importlib.util.spec_from_file_location('asr_guard',SCRIPTS/'check_dialogue_asr.py')
 asr=importlib.util.module_from_spec(spec);spec.loader.exec_module(asr)
 monkeypatch.setenv('H3_WHISPER_MODEL',str(tmp_path/'missing.pt'))
 with pytest.raises(RuntimeError,match='No automatic download'):asr.transcribe_segments('unused.wav',[], 'zh', ['test'])
