---
name: drama-doc-standard
description: 在 drama-production-skills 仓库中创建、更新、重构或审查技术文档、Skill 指南及架构决策记录时使用。强制执行事实检验原则、渐进式披露、上下文预算与 ADR 决策沉淀。
---

# Drama Documentation Standard (仓库文档与知识治理规范)

参考 `deepseek-harness` 的 `dsh-doc` 实践，本技能用于规范短剧工程知识、技能说明书与架构决策的写作质量，防止文档与真实代码漂移脱节。

## 适用场景
- 编写或更新任何技能的 `SKILL.md`；
- 撰写新的架构决策记录（ADR）或修改 `docs/` 下的系统架构文档；
- 编写或修改跨工序规约 `references/*.md`；
- 审查文档的真实性、命令可执行性与排版规范。

## 核心写作工作流

1. **分级定岗**：
   - 确定要写的文档属于哪一级（见 [doc-hierarchy.md](references/doc-hierarchy.md)）：
     - 技能调用入口 → 写入 `skills/<name>/SKILL.md`；
     - 细分工序知识/长篇手册 → 写入 `skills/<name>/references/<topic>.md`；
     - 跨工序全景/重大取舍/演进史 → 写入 `docs/`；
     - 生产数据示例/断场记录 → 写入 `examples/`。

2. **事实检验 (Fact-Check Procedure)**：
   - 运行每一个在文档中提及的命令（如 `python scripts/cinematic_audio_mixer.py ...`）；
   - 确保参数名、环境变量名与代码完全匹配；
   - 严禁书写未经验证的推测性指令。

3. **控制单体篇幅 (Progressive Disclosure)**：
   - 保持 `SKILL.md` 轻量且精准（100 行内），长篇规约外置到 `references/`；
   - 确保 Agent 只在需要时才按需读取特定 reference 文档。

4. **决策闭环**：
   - 若本次文档更新伴随核心行为变更（例如调整音频主路径或更改续接裁头逻辑），必须同步在 `docs/evolution-and-decisions.md` 中追加新的 ADR 条目。
