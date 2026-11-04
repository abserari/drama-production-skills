# 短剧工程审查清单 (Drama Code Review Checklist)

参考 `deepseek-harness` 的 `dsh-code-review` 标准，任何提交或审查 `drama-production-skills` 的改动时，必须对照本清单逐项审核，防止破坏性重构与架构退化。

---

## 1. 架构红线审核 (ADR Compliance)

- [ ] **严禁减步数提速 (ADR-05)**：代码中未将采样步数从 20 压减到 10，亦未引入未经音画分离验证的激进缓存。
- [ ] **台词前置与时序敏感 (ADR-04)**：提示词处理逻辑中，必须保证台词 `<Audio N>...说：<d>...</d>` 排在第一拍最前，动作描述整块后置于 `<d>` 标签后。
- [ ] **续接只传状态 (ADR-02)**：未在提示词中强行加入多秒的机位承接动作；续接钉帧裁切严格依据台账 `cont.frames` 字段。
- [ ] **原生音轨为主体 (ADR-01)**：交付链路默认保留 H3 原生多模态音轨，仅在严重吞字故障时转入备用 TTS。

## 2. 跨平台与路径安全 (Path Safety)

- [ ] **严禁物理绝对路径硬编码**：公共代码与技能中不得出现 `D:/...`、`C:/Users/...`、`/home/...` 等宿主机专属路径。
- [ ] **统一使用动态解析**：必须通过 `paths.py`、`os.environ.get()` 或跨平台路径库 (`pathlib.Path`) 解析 ComfyUI、Whisper 模型与项目目录。
- [ ] **防止内部污染**：脚本在执行时必须检查当前目录是否位于 skill 仓库内部，禁止将运行态断场、临时视频或日志写入 skill 树内。

## 3. 并发安全与状态一致性 (State & Concurrency)

- [ ] **原子化状态读写**：所有对 `progress.json`、`project.json`、`plan.json` 的写操作必须统一调用 `production_state.py` 的 `atomic_json()`，防止因中断造成 JSON 损坏。
- [ ] **设备独占锁**：涉及物理 GPU 推理或大显存占用脚本，应适配 `gpu_lock`，避免并发渲染导致爆显存（OOM）。

## 4. 资产与技能隔离 (Sanitization)

- [ ] **公共技能不夹带私货**：严禁将特定短剧的剧本、特定角色提示词或大体积未脱敏媒体直接合入公共技能目录；项目业务数据一律放置于外部项目目录或 `examples/`。
- [ ] **大文件过滤**：检查 `.gitignore`，避免误提交 `.mp4`、`.safetensors` 或临时运行态目录。

## 5. 验证闭环 (Verification Evidence)

- [ ] **单元测试通过**：运行 `pytest tests/` 全部通过。
- [ ] **断场零退化**：涉及检测器（ASR、门禁、光流）修改时，必须附带 `golden.py run` 的零 `REGRESSED` 输出记录。
