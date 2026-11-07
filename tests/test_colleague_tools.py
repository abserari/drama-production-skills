"""Behavior checks for colleague tools and bounded service recovery, no GPU work."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/comfy-h3-video-producer/scripts'
sys.path.insert(0, str(SCRIPTS))
import storyboard_json
import asset_check
import check_prompt_v2
import sop_run


def block(tmp_path, data):
    p = tmp_path / '分镜.md'
    p.write_text('``` shots-json\n' + json.dumps(data) + '\n```', encoding='utf-8')
    return p


def shot(**kw):
    return dict(no=1, size='close', camera='fixed', content='speaker', sec=2, transition='cut', **kw)


def test_storyboard_parses_spaced_fence_and_preserves_content(tmp_path):
    data = {'shots': [shot()]}
    assert storyboard_json.extract(block(tmp_path, data)) == data


@pytest.mark.parametrize('data', [[], {'shots':[None]}, {'shots':[shot(),shot()]},
    {'shots':[{**shot(),'sec':-1}]}, {'shots':[{**shot(),'sec':True}]},
    {'shots':[{**shot(),'sec':float('nan')}]}])
def test_invalid_storyboard_refuses_instead_of_creating_false_plan(tmp_path, data):
    with pytest.raises(SystemExit):
        storyboard_json.extract(block(tmp_path, data))


def test_asset_checker_handles_missing_corrupt_and_project_resolution(tmp_path):
    import cv2
    import numpy as np
    assert asset_check.check_one(str(tmp_path/'missing.png'))['fails']
    bad=tmp_path/'坏图.png'; bad.write_bytes(b'broken')
    assert asset_check.check_one(str(bad))['fails']
    p=tmp_path/'360p首帧.png'
    cv2.imencode('.png',np.full((352,640,3),100,dtype=np.uint8))[1].tofile(str(p))
    assert asset_check.check_one(str(p))['fails']
    assert not asset_check.check_one(str(p),min_edge=640,aspects=(640/352,),check_background=False)['fails']


def test_prompt_negation_does_not_hide_later_positive_sentence():
    body=check_prompt_v2.strip_neg_sentences('禁止表现悲伤。她非常愤怒。')
    assert '非常愤怒' in body
    assert '禁止表现悲伤' not in body


def test_service_unavailable_is_not_empty_queue(monkeypatch):
    def unavailable(*a,**k): raise ConnectionError('offline')
    monkeypatch.setattr(sop_run.paths,'http_json',unavailable)
    assert sop_run._queue_pids() is None
    monkeypatch.setattr(sop_run.paths,'http_json',lambda *a,**k: {'queue_running':[],'queue_pending':[]})
    assert sop_run._queue_pids()==(set(),set())


def test_watch_outage_stops_without_replacing_or_resubmitting_task(monkeypatch):
    record={'prompt_id':'known','status':'生成中','baseline':{}}
    monkeypatch.setattr(sop_run.paths,'require_project',lambda:None)
    monkeypatch.setattr(sop_run,'_wf',lambda:({'take1_prefix':'take'},{}))
    monkeypatch.setattr(sop_run,'seg_state',lambda seg:({'segs':{'s':record}},record))
    monkeypatch.setattr(sop_run,'_new_files',lambda *a:[])
    monkeypatch.setattr(sop_run,'_queue_pids',lambda:None)
    monkeypatch.setattr(sop_run.time,'sleep',lambda *a:None)
    monkeypatch.setattr(sop_run,'save',lambda *a:pytest.fail('outage must not change task'))
    monkeypatch.setattr(sop_run,'cmd_submit',lambda *a:pytest.fail('unexpected resubmit'))
    with pytest.raises(SystemExit) as e:
        sop_run.cmd_watch(SimpleNamespace(seg='s',timeout=999,poll=0))
    assert e.value.code==4
    assert record['prompt_id']=='known' and record['status']=='生成中'
