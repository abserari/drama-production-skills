"""Legacy entry cannot bypass the maintained skill's production gates."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def legacy():
    return load('legacy_batch_safety', ROOT / 'scripts/run_episodes_1_to_10_master.py')


@pytest.fixture
def project(tmp_path):
    ep = tmp_path / 'EP01_demo'
    (ep / 'prompts').mkdir(parents=True)
    plan = {'generation_mode': 't2v', 'segs': [
        {'seg': 'seg01', 'length': 100, 'dialogue': False}
    ]}
    (ep / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    (ep / 'prompts/seg01.txt').write_text(
        '\n'.join(f'[{section} 1] example' for section in
                  ('Shot', 'Subject', 'Action', 'Environment', 'Lighting', 'Audio', 'Quality')),
        encoding='utf-8')
    return tmp_path, ep, plan


def test_production_refuses_before_any_network_or_files(legacy, monkeypatch):
    monkeypatch.setattr(legacy, 'check_comfyui_alive', lambda **kw: pytest.fail('network called'))
    assert legacy.execute_production_pipeline(SimpleNamespace(dry_run=False)) == 2


def test_one_silent_t2v_shot_is_valid_static_input(legacy, project, capsys):
    root, _, _ = project
    assert legacy.execute_dry_run_pipeline(['EP01'], episodes_root=root) == 0
    out = capsys.readouterr().out
    assert '100% PASS' not in out
    assert '未验证 ComfyUI' in out


def test_required_keyframe_cannot_fall_back(legacy, project):
    root, ep, plan = project
    plan['generation_mode'] = 'i2v'
    (ep / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    assert legacy.execute_dry_run_pipeline(['EP01'], episodes_root=root) == 1


@pytest.mark.parametrize('data', [b'', b'not a real image' * 100])
def test_corrupted_keyframe_rejected(legacy, project, data):
    root, ep, _ = project
    (ep / 'seg01_keyframe.png').write_bytes(data)
    assert legacy.execute_dry_run_pipeline(['EP01'], episodes_root=root) == 1


def test_missing_requested_episode_not_success(legacy, project):
    root, _, _ = project
    assert legacy.execute_dry_run_pipeline(['EP01', 'EP02'], episodes_root=root) == 1


def test_empty_scope_and_out_of_range_not_success(legacy, project):
    root, _, _ = project
    assert legacy.execute_dry_run_pipeline([], episodes_root=root) == 1
    assert legacy.execute_dry_run_pipeline(['EP01'], start_seg=2, episodes_root=root) == 1


@pytest.mark.parametrize('overrides', [
    {'width': 848}, {'width': 0}, {'height': -16}, {'length': 0},
    {'length': True}, {'model_type': 'made-up'}, {'prompt_text': ''}, {'seed': -1},
])
def test_graph_builder_rejects_bad_values(overrides):
    render = load('render_core_safety', ROOT / 'skills/comfy-h3-render-core/scripts/h3_render_orchestrator.py')
    with pytest.raises(ValueError):
        render.build_h3_prompt_graph(**{'prompt_text': 'test', **overrides})


def test_graph_builder_imports_and_preserves_first_frame():
    render = load('render_core_valid', ROOT / 'skills/comfy-h3-render-core/scripts/h3_render_orchestrator.py')
    graph = render.build_h3_prompt_graph('test', first_frame_filename='frame.png')
    assert graph['6']['inputs']['first_frame'] == ['20', 0]
    assert graph['20']['inputs']['image'] == 'frame.png'
