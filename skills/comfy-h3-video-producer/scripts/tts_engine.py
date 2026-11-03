# -*- coding: utf-8 -*-
"""TTS 引擎封装 —— CosyVoice2 零样本克隆（音画分流的台词侧）。

模型只在进程内加载一次；对外的唯一接口是 synthesize()。
此文件本身不含权重，运行依赖 `H3_TTS_HOME`（默认 D:/H3AudioProd）布局：
    CosyVoice/       官方仓库（含 third_party/Matcha-TTS）
    models/CosyVoice2-0.5B   权重（ModelScope 下载）
    .venv/           py3.10 + torch cu128（RTX 5060 sm_120）
audioprod.py 的 gen 在缺 cosyvoice 时会自动用该 venv 重入，一般不用直接跑本文件。
"""
import os
import sys

ROOT = os.environ.get("H3_TTS_HOME", "D:/H3AudioProd")
REPO = os.path.join(ROOT, "CosyVoice")
MODEL_DIR = os.path.join(ROOT, "models", "CosyVoice2-0.5B")

_engine = None  # 进程级单例


class TTSEngine:
    def __init__(self, model_dir=MODEL_DIR):
        if not os.path.isdir(model_dir):
            raise SystemExit(f"[FATAL] 模型目录不存在: {model_dir}（先跑 H3_TTS_HOME 下 download_model.py）")
        # CosyVoice 要求把 Matcha-TTS 塞进 sys.path
        sys.path.insert(0, os.path.join(REPO, "third_party", "Matcha-TTS"))
        sys.path.insert(0, REPO)
        import torch
        # torch>=2.6 默认 weights_only=True，CosyVoice 的 checkpoint 会挂
        _orig_load = torch.load
        torch.load = lambda *a, **k: _orig_load(*a, **{**k, "weights_only": False})
        from cosyvoice.cli.cosyvoice import CosyVoice2
        self.model = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=True)

    def synthesize(self, text, ref_wav, ref_text, speed=1.0, out_path=None):
        """零样本克隆：text=要说的台词，ref_wav/ref_text=3~10s 参考音及其逐字稿。

        返回 (sample_rate, numpy 数组)；out_path 给了就同时写 24k wav。
        此版本 API：inference_zero_shot 直接收 wav 路径，内部自行加载/重采样。
        """
        import numpy as np
        import torchaudio
        chunks, sr = [], None
        for i in self.model.inference_zero_shot(text, ref_text, ref_wav,
                                                stream=False, speed=speed):
            chunks.append(i["tts_speech"])
            sr = i["tts_speech"].sr if hasattr(i["tts_speech"], "sr") else 24000
        if not chunks:
            raise RuntimeError(f"TTS 无输出: {text[:30]}")
        import torch
        audio = torch.cat(chunks, dim=1)  # [1, T]
        arr = audio.numpy().squeeze(0)
        if out_path:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            torchaudio.save(out_path, audio, sr, encoding="PCM_S", bits_per_sample=16)
        return sr, arr


def get_engine():
    global _engine
    if _engine is None:
        print("[tts] 加载 CosyVoice2（首次约 10-30 秒）...", flush=True)
        _engine = TTSEngine()
    return _engine


if __name__ == "__main__":
    # 冒烟：python tts_engine.py "你好" refs/S1.wav "参考逐字稿" out.wav
    text, ref_wav, ref_text, out = sys.argv[1:5]
    sr, _ = get_engine().synthesize(text, ref_wav, ref_text, out_path=out)
    print(f"[tts] OK {out} ({sr} Hz)")
