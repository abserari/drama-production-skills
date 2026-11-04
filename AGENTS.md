# AGENTS.md

> **AI 代理常驻指南**：本仓库遵循 Agent-First 与技能化治理原则。具体维护 SOP、工程门禁与执行规则**均在 `.agents/skills/` 的对应技能中维护与执行**，本文件仅作为顶层索引导航。

---

## 1. 技能导引 (Skills Map)

所有日常开发、生产与维护操作，请直接调用并执行对应的 Agent Skill：

### 仓库维护与质量治理 (Governance)
- **代码审查与红线检查**：使用 [`.agents/skills/drama-code-review`](.agents/skills/drama-code-review/SKILL.md) 审查 PR / 改动是否符合架构红线（禁止减步数、台词前置、路径安全等）。
- **推送与提测门禁**：使用 [`.agents/skills/drama-pre-push-checks`](.agents/skills/drama-pre-push-checks/SKILL.md) 自动化执行卫生检查、测试套件、路径安全与断场回归。
- **文档与知识规范**：使用 [`.agents/skills/drama-doc-standard`](.agents/skills/drama-doc-standard/SKILL.md) 遵循事实检验原则（Fact-Check）与渐进式披露（Progressive Disclosure）。

### 短剧工业化生产工序 (Production Pipeline)
- **总制片调度**：[`.agents/skills/drama-production-director`](.agents/skills/drama-production-director/SKILL.md)（多工序串联、断点续产）
- **导演分镜**：[`.agents/skills/drama-director-staging`](.agents/skills/drama-director-staging/SKILL.md)（台词与节拍编排）
- **视觉与首帧**：[`.agents/skills/drama-keyframe-forge`](.agents/skills/drama-keyframe-forge/SKILL.md)（首帧门禁与视觉资产）
- **物理渲染**：[`.agents/skills/comfy-h3-render-core`](.agents/skills/comfy-h3-render-core/SKILL.md)（ComfyUI H3 物理渲染）
- **音频声场**：[`.agents/skills/drama-audio-soundstage`](.agents/skills/drama-audio-soundstage/SKILL.md)（侧链压限与混音）
- **后期超分**：[`.agents/skills/drama-finishing-upscaler`](.agents/skills/drama-finishing-upscaler/SKILL.md)（自动拼接与 4K 超分）
- **全流程质检**：[`.agents/skills/drama-production-review`](.agents/skills/drama-production-review/SKILL.md)（独立验收把关）
- **单技能直通**：[`.agents/skills/comfy-h3-video-producer`](.agents/skills/comfy-h3-video-producer/SKILL.md)（全工序向后兼容）

---

## 2. 事实来源 (Sources of Truth)

- **架构决策与历史演进 (ADR)**：[`docs/evolution-and-decisions.md`](docs/evolution-and-decisions.md)
- **评测与验收基准**：[`docs/agent-evaluation.md`](docs/agent-evaluation.md)
- **官方原始指南**：`skills/comfy-h3-video-producer/references/official/`

---

## 3. 同步纪律

技能源码与 `.agents/skills/` 保持同构。更新技能后运行：
```bash
python scripts/sync_skills.py --target .agents/skills --apply
```
