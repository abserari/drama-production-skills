# -*- coding: utf-8 -*-
"""统一路径与 HTTP：迁移机器 / 多项目并行 / 工作流变更时，只改环境变量，不改脚本。

设计原则（v3，为"残留污染"这类问题做的结构性修复）
--------------------------------------------------
1. **运行时数据一律不写进技能目录。** 技能目录只读放代码与模板；state/checks/帧/tmp
   全部落在"项目目录"（含 project.json 的那个目录）。若解析结果指向技能目录，直接判定
   为未就绪（PROJECT_DIR=None），需要的人自己调 require_project() 报错 —— 这样"忘了设
   项目目录"不会静默污染下一个工程。
2. **项目目录解析顺序**：H3_PROJECT_DIR > H3_PROJECT > 从 cwd 向上找 `生产/project.json`
   （或 cwd 自身有 project.json）。
3. **所有本地 HTTP 一律绕开系统代理**（踩坑 15：HTTP_PROXY 会把 127.0.0.1 变成 502）。

环境变量
--------
  H3_COMFY        ComfyUI 地址              默认 http://127.0.0.1:8188
  H3_OUTPUT_DIR   ComfyUI 输出目录          默认 D:/Comfy-Desktop/ComfyUI-Shared/output
  H3_INPUT_DIR    ComfyUI 输入目录          默认 D:/Comfy-Desktop/ComfyUI-Shared/input
  H3_PROJECT_DIR  本项目目录（必须显式或可推导）  无默认
  H3_VOICE_CARD   声线卡 json               默认 <项目>/voice_card.json，其次技能模板
  H3_FFMPEG       ffmpeg 可执行文件         默认自动探测
"""
import json
import os
import shutil
import sys
import urllib.request


def force_utf8_stdio():
    """Windows 控制台默认 GBK/CP936：中文 + emoji 输出会直接 UnicodeEncodeError
    挂起，子进程输出 decode 也可能 UnicodeDecodeError。所有脚本都 import 本模块，
    在导入时统一把 stdout/stderr 切到 UTF-8（errors=replace 兜底，永不崩）。"""
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdio()

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
MARK = "project.json"


# ── 项目目录 ─────────────────────────────────────────────
def _walk_up_project():
    d = os.path.abspath(os.getcwd())
    while True:
        for cand in (os.path.join(d, "生产"), d):
            if os.path.isfile(os.path.join(cand, MARK)):
                return os.path.abspath(cand)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _resolve_project():
    p = os.environ.get("H3_PROJECT_DIR")
    if p:
        return os.path.abspath(p)
    p = os.environ.get("H3_PROJECT")
    if p:
        p = os.path.abspath(p)
        return os.path.dirname(p) if p.endswith(MARK) else p
    return _walk_up_project()


def _same(a, b):
    n = lambda x: os.path.normcase(os.path.abspath(x)).rstrip("\\/")
    return n(a) == n(b)


def _inside_skill_tree(path):
    root = os.path.normcase(os.path.realpath(os.path.dirname(SKILL)))
    try:
        return os.path.commonpath([os.path.normcase(os.path.realpath(path)), root]) == root
    except ValueError:  # Different Windows drives cannot contain one another.
        return False


PROJECT_DIR = _resolve_project()
if PROJECT_DIR and _inside_skill_tree(PROJECT_DIR):
    # 硬护栏：绝不把 state/checks 写进技能目录
    PROJECT_DIR = None


def require_project():
    if not PROJECT_DIR:
        raise SystemExit(
            "[FATAL] 未确定项目目录。运行时数据不允许写进技能目录。\n"
            "  先建工程： python scripts/h3proj.py new <剧本目录>/生产 --name <片名>\n"
            "  或设环境变量 H3_PROJECT_DIR 指向含 project.json 的目录。")
    return PROJECT_DIR


def _p(*parts):
    return os.path.join(PROJECT_DIR, *parts) if PROJECT_DIR else None


PROJECT_JSON = _p(MARK)
CHECKS_DIR = _p("checks")
TMP_AUDIO = _p(os.path.join("checks", "_audio_tmp"))
STATE = _p("state.json")
PROGRESS = _p("progress.json")
PLAN = _p("plan.json")
PLAN_MD = _p("plan.md")
WF_MAP = _p("wf_map.json")
WF_SNAPSHOT = _p("wf_snapshot.json")
SEG_DIR = _p("segments")
FINISH_DIR = _p("成片")
BLACKLIST_PATH = _p(os.path.join("checks", "blacklist.json"))
BLACKLIST = BLACKLIST_PATH  # 兼容旧名

# ── ComfyUI 与外部工具 ───────────────────────────────────
COMFY = os.environ.get("H3_COMFY", "http://127.0.0.1:8188").rstrip("/")
COMFY_ROOT = os.environ.get("COMFYUI_PATH", r"C:/AI/ComfyUI" if os.name == "nt" else os.path.expanduser("~/ComfyUI"))
OUTPUT_DIR = os.environ.get("H3_OUTPUT_DIR", os.path.join(COMFY_ROOT, "output"))
INPUT_DIR = os.environ.get("H3_INPUT_DIR", os.path.join(COMFY_ROOT, "input"))


def _find_ffmpeg():
    p = os.environ.get("H3_FFMPEG")
    if p and os.path.exists(p):
        return p
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    hit = shutil.which("ffmpeg")
    return hit or "ffmpeg"


FFMPEG = _find_ffmpeg()
FFPROBE = os.environ.get("H3_FFPROBE") or (
    os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")
    if os.path.exists(os.path.join(os.path.dirname(FFMPEG), "ffprobe.exe")) else "ffprobe")
# ffprobe 在不少 Windows 便携包/网盘残片里是缺的（夸克未下完会把 exe 截断）。
# 缺了不影响本技能的探测（h3proj 会退回 ffmpeg -i 解析），但**段尾归位**那侧
# 会硬失败（报"收片后无法确认视频帧数"），所以这里要如实报出来。
FFPROBE_OK = bool(FFPROBE) and (os.path.isfile(FFPROBE) or bool(shutil.which(FFPROBE)))


def _voice_card():
    p = os.environ.get("H3_VOICE_CARD")
    if p:
        return p
    local = _p("voice_card.json")
    if local and os.path.isfile(local):
        return local
    return os.path.join(HERE, "voice_card.json")


VOICE_CARD = _voice_card()


def tmp_audio():
    """临时 wav 目录：有项目就落项目内，没有就退回系统临时目录（不污染技能目录）。"""
    if TMP_AUDIO:
        os.makedirs(TMP_AUDIO, exist_ok=True)
        return TMP_AUDIO
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "h3_audio")
    os.makedirs(d, exist_ok=True)
    return d


# ── HTTP（一律绕代理） ──────────────────────────────────
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(path, payload=None, timeout=60):
    url = COMFY + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with _OPENER.open(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body) if body else {}


def comfy_alive(timeout=5):
    try:
        http_json("/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


def ensure_cv2_or_reexec(script=None):
    """入口自愈：系统 python 往往没装 cv2，质检跑到一半才 ModuleNotFoundError，
    而那时候一采已经跑完、二采三采在路上，等于白烧一次生成。

    这里在**入口**就检查，缺 cv2 就静默换到装好 cv2 的解释器
    （优先 H3_PY，其次 WorkBuddy 的默认 venv），把参数原样带过去。
    """
    try:
        import cv2  # noqa: F401
        return
    except Exception:
        pass
    import subprocess
    import sys
    script = script or os.path.abspath(sys.argv[0])
    cands = [os.environ.get("H3_PY"),
             os.path.join(os.environ.get("USERPROFILE", ""), ".workbuddy", "binaries",
                          "python", "envs", "default", "Scripts", "python.exe")]
    me = os.path.normcase(os.path.abspath(sys.executable))
    for exe in cands:
        if not exe or not os.path.isfile(exe):
            continue
        if os.path.normcase(os.path.abspath(exe)) == me:
            continue
        try:
            r = subprocess.run([exe, "-c", "import cv2"], capture_output=True, timeout=60)
        except Exception:
            continue
        if r.returncode == 0:
            print(f"[env] 当前解释器没有 cv2，已切到 {exe}")
            sys.stdout.flush()
            sys.exit(subprocess.call([exe, script] + sys.argv[1:]))


def describe():
    return {
        "comfy": COMFY,
        "alive": comfy_alive(),
        "project_dir": PROJECT_DIR,
        "output_dir": OUTPUT_DIR,
        "input_dir": INPUT_DIR,
        "voice_card": VOICE_CARD,
        "ffmpeg": FFMPEG,
        "ffprobe": FFPROBE if FFPROBE_OK else "缺失（h3proj 走 ffmpeg 兜底；段尾归位需装 ffprobe 或探帧兜底补丁）",
        "ready": bool(PROJECT_DIR and os.path.isfile(PROJECT_JSON or "")),
    }


if __name__ == "__main__":
    print(json.dumps(describe(), ensure_ascii=False, indent=1))
    if not PROJECT_DIR:
        print("\n[!] 项目目录未就绪：状态/帧/临时文件不会写进技能目录（这是故意的）。")
