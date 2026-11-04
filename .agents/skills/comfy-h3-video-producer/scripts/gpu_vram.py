#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""显存回收（VRAM reclamation）——给「中断后必清、段前必检」用。

## 为什么需要它

H3 工作流末尾挂着 `BanZhang_VRAM_Cleaner`（323/324，卸载模型+清缓存），
**正常跑完**时由它把显存交还。但一旦 `/interrupt`（AUTO_ABORT、手动 abort），
执行链在第 N 步就断了，清理节点根本没轮到 —— 模型与执行缓存原样留在显存里。

下一次任务启动时 `BanZhang_VRAM_Guard`（264，预留 1.0GB）看到可用不足，
就判定超限，于是**每采一步都把模型卸载再重载**。实测代价：

    脏显存：299.90s/it  × 6 步 ≈ 30 分钟（GPU 100% 但只有 42W，空转等搬运）
    干净后： 45.18s/it  × 6 步 ≈ 4 分钟（GPU 100%，81W）

所以 `/interrupt` 之后必须补发 `/free`，把 Cleaner 没做完的事做完。

## 三个接口的差别（这是最关键的一点）

- `/interrupt`  只让采样循环在当前步结束后抛异常退出。**模型不动**。
- `/queue clear` 只清掉还没开始的任务。对已加载的模型无效。
- `/free`       `{"unload_models": true, "free_memory": true}`
                前者把模型从 ComfyUI 的 model cache 卸载，后者执行
                `gc.collect()` + `torch.cuda.empty_cache()`。
                **任务运行期间调用会被排队到当前执行结束，等于无效**，
                所以顺序必须是 中断 → 等队列空 → free。

## 清不掉的残留（正常，不用管）

CUDA context 本身约 300-500MB、cuBLAS workspace 等，`/free` 不收。
实测清完显存从 7521 MiB 降到 1718 MiB 就是到位的状态。要连这部分也清，
只能重启 ComfyUI 进程。

用法：
    python gpu_vram.py --check     # 只报告，不动手
    python gpu_vram.py --clean     # 中断→清队列→free→复检
    python gpu_vram.py --ensure    # 脏了才清（submit 前的钩子用这个）
"""
import argparse
import time

import paths

# 清完后残留约 1.7GB 属于正常（CUDA context + workspace）。
# 可用来判断「脏」的阈值：空闲低于这个数，说明模型还压在显存里。
DIRTY_FREE_GB = 1.2


def stats():
    """返回 {total, free, used}（字节）。接口不可用时返回 None。"""
    try:
        st = paths.http_json("/system_stats", timeout=15)
    except Exception:
        return None
    for d in st.get("devices") or []:
        tot = d.get("vram_total") or 0
        free = d.get("vram_free") or 0
        if tot:
            return {"total": tot, "free": free, "used": tot - free,
                    "name": d.get("name") or "cuda"}
    return None


def queue_len():
    try:
        q = paths.http_json("/queue", timeout=15)
        return len(q.get("queue_running") or []), len(q.get("queue_pending") or [])
    except Exception:
        return -1, -1


def free(wait=4.0, verbose=True):
    """补做 BanZhang_VRAM_Cleaner 的工作：中断 → 清队列 → 等节点真正退出 → 卸模型清缓存。

    用户规则（2026-10-31）：每次中断后必须等显存完全释放，才允许下一次重抽，
    避免频繁强杀导致显存暴碎、残留孤儿进程。`wait` 是中断后最短等待秒数
    （默认 4.0）；实际以「队列 running+pending 全空」为准，4 秒后还没清空
    就继续轮询（最多再等 10 秒）—— 太早发 /free 会被排队到执行结束后才
    生效，等于没发。
    """
    for ep, payload in (("/interrupt", {}), ("/queue", {"clear": True})):
        try:
            paths.http_json(ep, payload, timeout=20)
        except Exception:
            pass  # /interrupt 在没有任务时会报错，属正常
    if wait:
        time.sleep(wait)
    # 等当前节点真正退出：队列全空才说明中断完成，才能发 /free
    t0 = time.time()
    while time.time() - t0 < 10.0:
        run, pend = queue_len()
        if run <= 0 and pend <= 0:
            break
        time.sleep(0.5)
    ok = True
    try:
        paths.http_json("/free", {"unload_models": True, "free_memory": True}, timeout=20)
    except Exception as e:
        ok = False
        if verbose:
            print(f"[vram] /free 失败：{type(e).__name__} {e}")
    # gc + empty_cache 落袋需要 1-2 秒；若空闲没回升到干净水位，补一轮再等
    time.sleep(1.5)
    s = stats()
    if s and s["free"] < DIRTY_FREE_GB * 1e9:
        time.sleep(2.0)
        try:
            paths.http_json("/free", {"unload_models": True, "free_memory": True}, timeout=20)
        except Exception:
            pass
        time.sleep(1.5)
        s = stats()
    if verbose and s:
        print(f"[vram] 已释放：空闲 {s['free']/1e9:.2f} GB / 总 {s['total']/1e9:.2f} GB"
              f"（已用 {s['used']/1e9:.2f} GB）")
    return ok


def is_dirty(threshold_gb=DIRTY_FREE_GB):
    """显存里还压着模型、且没有任务在跑 —— 就是脏的。"""
    s = stats()
    if not s:
        return False, None
    run, pend = queue_len()
    dirty = (run == 0 and pend == 0 and s["free"] < threshold_gb * 1e9)
    return dirty, s


def ensure_clean(threshold_gb=DIRTY_FREE_GB, verbose=True):
    """submit 前的钩子：脏了就清，干净就放过。

    正常跑完的段由 323/324 Cleaner 收尾，显存空闲 ≥1.7GB，这里不会动手；
    只有中断/异常退出留下的脏显存才会被清掉。
    """
    dirty, s = is_dirty(threshold_gb)
    if s is None:
        if verbose:
            print("[vram] 取不到显存状态（ComfyUI 没开？），跳过自检")
        return False
    if not dirty:
        if verbose:
            print(f"[vram] 显存自检 OK：空闲 {s['free']/1e9:.2f} GB")
        return False
    if verbose:
        print(f"[vram] 显存脏（空闲仅 {s['free']/1e9:.2f} GB，无任务在跑）"
              f"→ 补做清理，避免下一步每采都卸载重载")
    free(wait=0, verbose=verbose)
    return True


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只报告状态")
    g.add_argument("--clean", action="store_true", help="中断→清队列→free→复检")
    g.add_argument("--ensure", action="store_true", help="脏了才清")
    a = ap.parse_args()

    if a.check:
        s = stats()
        if not s:
            print("[vram] 取不到显存状态（ComfyUI 没开？）")
            return 1
        run, pend = queue_len()
        print(f"[vram] {s['name']}")
        print(f"  总 {s['total']/1e9:.2f} GB ｜ 空闲 {s['free']/1e9:.2f} GB"
              f" ｜ 已用 {s['used']/1e9:.2f} GB")
        print(f"  队列：运行 {run} / 排队 {pend}")
        dirty, _ = is_dirty()
        print(f"  判定：{'脏（建议 --clean）' if dirty else '干净'}")
        return 0

    if a.clean:
        free(wait=4.0)
        return 0

    ensure_clean()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
