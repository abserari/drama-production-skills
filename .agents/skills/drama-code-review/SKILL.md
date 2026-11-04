---
name: drama-code-review
description: 在 drama-production-skills 仓库审查代码变更、Pull Request 或技能改造时使用。依据 6 大核心架构决策（ADR）、防御式设计规范、路径安全性、并发安全与黄金集回归标准进行深度代码审查。
---

# Drama Code Review (短剧代码与技能合规审查)

参考 `deepseek-harness` 的 `dsh-code-review` 实践，本技能旨在确保仓库内的每一次代码迭代、技能增强或缺陷修复均严格对齐既定架构标准，防止引入隐藏退化。

## 适用场景
- 审查针对 `drama-production-skills` 的 Pull Request 或分支 Diff；
- 维护者在合并代码前进行架构与防御性检查；
- 开发者自查本次改动是否符合工程规范。

## 审查指引与流程

1. **确定改动范围**：
   ```bash
   git diff --stat origin/main...HEAD
   ```

2. **对照核心清单逐项审核**：
   打开并核对 [review-checklist.md](references/review-checklist.md)：
   - **ADR 红线合规**：台词是否前置？是否私自压缩了采样步数？
   - **路径与跨平台安全**：是否有写死的物理盘符或个人用户目录？
   - **状态安全性**：JSON 写入是否使用了 `atomic_json` 防并发损坏？
   - **公共库防污染**：是否将特定剧本的专有数据写进了公共技能？

3. **执行自动化门禁校验**：
   要求提交人提供或直接运行：
   ```bash
   python .agents/skills/drama-pre-push-checks/scripts/pre_push_check.py
   ```

4. **审查决策与交付结论**：
   - 重点关注“正确性、生命周期安全性、向后兼容性与架构红线”；
   - 发现阻断性问题（如破坏 ADR 或硬编码路径）必须标出明确阻断原因与修复建议；
   - 审查通过后方可推进合入。
