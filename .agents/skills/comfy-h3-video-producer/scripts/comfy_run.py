# -*- coding: utf-8 -*-
"""Submit a converted API-format workflow to ComfyUI, poll, and collect outputs.

Usage:
  python comfy_run.py <api.json> [--watch]

No --watch: submit only, print prompt_id.
--watch: poll /history until done, then print output files.
"""
import json
import sys
import time
import urllib.request
import urllib.error

COMFY = "http://127.0.0.1:8188"
CLIENT_ID = "workbuddy-bridge"


def api(path, payload=None, timeout=30):
    url = COMFY + path
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def submit(api_json_path, overrides=None):
    p = json.load(open(api_json_path, encoding="utf-8"))
    if overrides:
        for nid, patch in overrides.items():
            if nid in p:
                for k, v in patch.items():
                    if v is None:
                        p[nid]["inputs"].pop(k, None)  # None = 删除该输入
                    else:
                        p[nid]["inputs"][k] = v
            else:
                raise KeyError(f"node {nid} not in workflow")
    res = api("/prompt", {"prompt": p, "client_id": CLIENT_ID}, timeout=60)
    return res


def queue_status():
    return api("/queue")


def history(prompt_id):
    h = api(f"/history/{prompt_id}")
    return h.get(prompt_id)


def collect_outputs(hist):
    files = []
    for node_id, node_out in (hist.get("outputs") or {}).items():
        for kind, items in node_out.items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("filename"):
                        files.append({"node": node_id, "type": kind, **it})
    return files


def watch(prompt_id, timeout_hours=4):
    t0 = time.time()
    last_q = ""
    while time.time() - t0 < timeout_hours * 3600:
        h = history(prompt_id)
        if h:
            status = h.get("status", {})
            print("status:", status.get("status_str"),
                  "| completed:", status.get("completed"), flush=True)
            if status.get("completed") or status.get("status_str") in ("error", "failed"):
                return h
        q = queue_status()
        running = len(q.get("queue_running", []))
        pending = len(q.get("queue_pending", []))
        cur = f"running={running} pending={pending}"
        if cur != last_q:
            print(cur, flush=True)
            last_q = cur
        time.sleep(15)
    raise TimeoutError("watch timed out")


if __name__ == "__main__":
    wf = sys.argv[1]
    watch_mode = "--watch" in sys.argv
    overrides = None
    if "--overrides" in sys.argv:
        overrides = json.load(open(sys.argv[sys.argv.index("--overrides") + 1], encoding="utf-8"))
    r = submit(wf, overrides)
    pid = r.get("prompt_id")
    if r.get("error"):
        print("SUBMIT ERROR:", json.dumps(r, ensure_ascii=False)[:2000])
        sys.exit(1)
    print("prompt_id:", pid, "| number:", r.get("number"))
    if watch_mode:
        h = watch(pid)
        msgs = h.get("status", {}).get("messages", [])
        for m in msgs:
            if m and m[0] in ("execution_error", "execution_interrupted"):
                print("EXEC ERROR:", json.dumps(m, ensure_ascii=False)[:3000])
        for f in collect_outputs(h):
            print("OUT:", f)
