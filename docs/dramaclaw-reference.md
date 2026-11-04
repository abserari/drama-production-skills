# 源码参考
本地克隆：C:/Users/34903/AppData/Local/Temp/dramaclaw-review-6e3e7710
固定提交：c7d9f0e459496b7d0b1251b3d9c95a3484d409bc。

workflow_preflight.py：实际能力检查 → 工序 SOP 前置检查。
workflow_transactions.py：局部修改 → 技能替换记录受影响工序。
workflow_runs.py、test_workflow_run_failure_guard.py：幂等与回执 → 现有提交脚本记录任务并核对。
verification/version_hash.py：实际提示词哈希 → production_state 指纹。
agent-kit/scripts/sync_skill.py：发布一致性 → sync_skills.py。
verification/convergence_log.py：改善记录 → 审查 fixed/residual/new_issues。

已运行上游发布一致性和五宿主配置解析并通过；未运行上游完整测试。独立实现上述机制，不移植源代码、网关、前端或平台。其创作规则不视作通用标准；其收敛日志不等于完整自动进化。
