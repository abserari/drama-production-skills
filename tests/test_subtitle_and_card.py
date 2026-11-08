# -*- coding: utf-8 -*-
"""Unit tests for subtitle alignment and ASS subtitle generation."""

import sys
from pathlib import Path
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "drama-finishing-upscaler" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import drama_subtitles_and_cards as dsc


def test_seconds_to_ass_time():
    assert dsc.seconds_to_ass_time(0.0) == "0:00:00.00"
    assert dsc.seconds_to_ass_time(65.43) == "0:01:05.43"
    assert dsc.seconds_to_ass_time(3661.05) == "1:01:01.05"


def test_align_with_script():
    whisper_segments = [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "耗付心的风沙还是这么强人",
            "words": [
                {"word": "耗", "start": 1.0, "end": 1.2},
                {"word": "付", "start": 1.2, "end": 1.4},
                {"word": "心", "start": 1.4, "end": 1.6},
                {"word": "的", "start": 1.6, "end": 1.8},
                {"word": "风", "start": 1.8, "end": 2.0},
                {"word": "沙", "start": 2.0, "end": 2.3},
                {"word": "还", "start": 2.3, "end": 2.5},
                {"word": "是", "start": 2.5, "end": 2.6},
                {"word": "这", "start": 2.6, "end": 2.7},
                {"word": "么", "start": 2.7, "end": 2.8},
                {"word": "强", "start": 2.8, "end": 2.9},
                {"word": "人", "start": 2.9, "end": 3.0},
            ]
        }
    ]
    script = "霍普金斯的风沙还是这么呛人"
    aligned = dsc.align_with_script(whisper_segments, script)
    assert len(aligned) == 1
    # 验证文字校准为剧本原台词
    assert aligned[0]["text"] == "霍普金斯的风沙还是这么呛人"
    # 验证字级时间戳被完整保留
    assert aligned[0]["words"][0]["word"] == "霍"
    assert aligned[0]["words"][0]["start"] == 1.0


def test_build_ass_subtitles(tmp_path):
    out_ass = tmp_path / "test.ass"
    segments = [
        {
            "start": 0.5,
            "end": 2.0,
            "text": "你好世界",
            "words": [
                {"word": "你", "start": 0.5, "end": 0.8},
                {"word": "好", "start": 0.8, "end": 1.2},
                {"word": "世", "start": 1.2, "end": 1.6},
                {"word": "界", "start": 1.6, "end": 2.0},
            ]
        }
    ]
    dsc.build_ass_subtitles(segments, out_ass, width=1080, height=1920, is_vertical=True)
    assert out_ass.exists()
    content = out_ass.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "DramaStandard" in content
    assert r"{\k30}你{\k40}好{\k40}世{\k40}界" in content
