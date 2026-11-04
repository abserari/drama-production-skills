---
name: drama-pre-push-checks
description: 在 drama-production-skills 仓库提交、创建 Pull Request 或推送前执行本地最小充分性验证。检查环境卫生、运行单元测试、校验路径安全性与黄金集断场回归，确保零退化与可复现证据交付。
---

# Drama Pre-Push Checks (仓库推送前质检门禁)

参考 `deepseek-harness` 的 `dsh-pre-push-checks` 实践：在推送任何改动前，必须运行本地最小且充分的验证证据，严禁在未经过真实执行检验的情况下直接合入代码。

## 适用场景
- 提交前自检代码质量与测试覆盖；
- 修改了检测器（`check_dialogue_asr.py`、`keyframe_gate.py`、`h3proj.py` 等）；
- 修改了工作流或核心路径定义；
- 准备推送分支或向主分支提交 PR。

## 核心质检流程

1. **一键执行自动化预检门禁**：
   ```bash
   python .agents/skills/drama-pre-push-checks/scripts/pre_push_check.py
   ```

2. **门禁检查项与通过标准**：
   - **工作区卫生 (Workspace Hygiene)**：严禁将临时文件（`*.tmp`, `*.log`, `*.bak`）或未通过 LFS 的大媒体（`*.mp4`, `*.safetensors`, `*.7z`）暂存或提交；
   - **单元测试 (Unit Tests)**：`pytest tests/` 必须 100% 通过（当前基线 40 个测试用例全部通过）；
   - **路径安全性 (Path Safety)**：严禁在公共技能或核心脚本中硬编码任何机器专属物理绝对路径（如 `D:/...`、`C:/Users/...`、`/home/...`），必须使用 `paths.py` 或环境变量进行动态跨平台解析；
   - **断场回归 (Golden Regression)**：当涉及检测器逻辑、门禁阈值或光流算法修改时，必须运行 `python skills/comfy-h3-video-producer/scripts/golden.py run`，确保 16 个断场案例零出现 `REGRESSED`（新错法）。

3. **证据记录**：
   在提交信息或 Pull Request 描述中，附上预检脚本输出的通过摘要作为真实交付证据。
