"""Small persistence and evidence helpers; no scheduler or command interface."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import tempfile


def atomic_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.name + ".", suffix=".tmp", delete=False) as f:
            name = f.name
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    if os.path.getsize(path) == 0:
        raise ValueError(f"Empty artifact: {path}")
    return h.hexdigest()


def require_artifact(path, expected):
    if not expected or file_hash(path) != expected:
        raise ValueError(f"Missing or stale artifact evidence: {path}")


@contextlib.contextmanager
def gpu_lock(server):
    """OS advisory lock, released on process exit; shared by installed skill copies."""
    key = hashlib.sha256(str(server).encode()).hexdigest()[:16]
    name = Path(tempfile.gettempdir()) / ("drama-gpu-" + key + ".lock")
    f = open(name, "a+b")
    locked = False
    try:
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as e:
            raise RuntimeError("GPU operation is owned by another process") from e
        yield
    finally:
        if locked:
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def render_context(project):
    """Only render-affecting project decisions; mixing remains a downstream stage."""
    production = project.get("production") or {}
    selected = project.get("selected_skills")
    nested = production.get("selected_skills")
    if selected is not None and nested is not None and selected != nested:
        raise ValueError("Conflicting selected_skills records; reconcile project before production")
    selected = selected if selected is not None else nested or {}
    render_skills = {k: v for k, v in selected.items()
                     if not any(word in k.lower() for word in ("audio", "sound", "mix", "finishing", "upscale", "review"))}
    return fingerprint({"selected_skills": render_skills, "route": production.get("route"), "language": production.get("language"), **{k: project.get(k) for k in
                        ("render_settings", "visual_style_version", "production_path", "requires_keyframe")}})


def require_configured_reviews(project_dir, plan, stage_id):
    """Explicit required review references; unverifiable evidence never releases output."""
    base = Path(project_dir).resolve()
    for entry in plan.get("required_reviews", []):
        if entry.get("stage_id") not in (stage_id, "*") or entry.get("mode", "blocking") != "blocking":
            continue
        review = read_json(base / entry["review_path"])
        if review.get("status") != "passed" or not review.get("evidence"):
            raise ValueError("Required review has not passed with evidence")
        if review.get("reviewer_kind") == "human" and not review.get("human_source"):
            raise ValueError("Human review needs actual user input reference")
        if entry.get("reviewer_kind") and review.get("reviewer_kind") != entry["reviewer_kind"]:
            raise ValueError("Wrong reviewer kind")
        require_artifact(base / entry["artifact_path"], review.get("artifact_sha256"))


def connected_first_frame(graph, filename, input_dir):
    """Require the declared image bytes on the actual first-frame dependency path."""
    expected = file_hash(filename)
    def visit(node_id, seen):
        if node_id in seen:
            return False
        seen = seen | {node_id}
        node = graph.get(str(node_id), {})
        inputs = node.get("inputs", {})
        if node.get("class_type") == "LoadImage":
            path = Path(input_dir) / str(inputs.get("image", ""))
            return path.is_file() and file_hash(path) == expected
        return any(visit(value[0], seen) for value in inputs.values()
                   if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str))
    return any(visit(value[0], set()) for node in graph.values()
               for name, value in node.get("inputs", {}).items()
               if name == "first_frame" and isinstance(value, list) and len(value) == 2)
