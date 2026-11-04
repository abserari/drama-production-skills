# Skill 驱动短剧制作
入口：skills/drama-production-director/SKILL.md。按需选择工序 skill，独立审查由 drama-production-review 执行。

无需统一 CLI 或 MCP。现有脚本是 SOP 内部工具；旧十集母调度只用于静态检查，生产改走受检 H3 SOP。

模板：skills/drama-production-director/assets/project-template/。
发布：python scripts/sync_skills.py --apply；检查省略 --apply。只同步受维护源文件，不删除本地多余文件。
导入：python scripts/import_legacy_project.py SOURCE TARGET；单独目标目录，冲突阻塞，历史素材待验证。
测试：python -m pytest tests -q。

参考：docs/dramaclaw-reference.md；验收：docs/agent-evaluation.md；实际实施状态：docs/implementation-status.md。


已完成的实例：examples/skill-replacement/（实际文本配方替换与回滚）；examples/agent-evaluation/（可重放跨 agent 输入）。
本机实测：工作区 production-validation/native-h3/（三镜、一次局部返工、拼接、1080p 及音频包保留验证）；检查结论和限制见 docs/implementation-status.md。
历史部署文档保存于 docs/legacy-readme.md；项目专属旧状态已移到 examples/legacy-project-data，不再混在技能代码中。
