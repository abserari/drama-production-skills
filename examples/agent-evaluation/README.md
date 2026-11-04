# 跨 Agent 验收输入
将 input-cases.json 中每个案例展开到独立目录，每个 JSON 对象存为同名 .json，task 存 task.md，files 存指定文件。每个案例重复三次；全新会话只传总协调技能、关联文档、案例目录和 task。

统一结果字段见 ../../docs/agent-evaluation.md，验证脚本为 ../../scripts/verify_agent_evaluation.py。该脚本核对实际规划、输入、损坏媒体、b 状态、原任务编号和回滚证据，不能代替对真实媒体质量的审查。

本地已完成的原始记录在工作区 production-validation/agent-usage，24 项为 Codex 独立会话使用验证。Gemini 单独记录；没有真实调用不能记作 Gemini 通过。

准备全新验证目录：python scripts/prepare_agent_evaluation.py ABS_TARGET（从仓库根执行）。
让真实 agent 在各案例执行 task.md 后，运行 python scripts/verify_agent_evaluation.py ABS_TARGET 核对实际记录。
