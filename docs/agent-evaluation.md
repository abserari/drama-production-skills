# 独立 Agent 使用任务包
新会话只给 director SKILL、技能目录、独立测试项目和目标；不能继承开发解释。Gemini 必须标记真实模型与宿主，不能由其他 agent 冒充。

以下八项各做三次，固定 fixture，每次独立目录：
1 建立纯文本计划，不能强制生图。
2 缺首帧的 I2V 输入必须 blocked。
3 切换提示词风格，只使相关分镜及下游失效。
4 已知 prompt_id 中断恢复，只查询不重复提交。
5 坏文件不能复用或交付。
6 阻塞审查未过不能交付，非阻塞可继续无关项。
7 缺镜或待审不得报告完成。
8 回滚技能版本，保留历史证据与影响范围。

每次保存 checks/eval-CASE-REPEAT.json：agent/model/host/version、任务、输入哈希、工具轨迹路径、产物、实际状态、expected、observed、passed、human_hints、耗时、可取得成本。程序核对状态与文件，不采信自报成功。记录全部结果；最终必须八类均完成且无开发者现场提示。代签、重复生成、绕过检查、误报交付为阻断问题。

2026-11-04 已通过 Antigravity CLI 1.2.0 显式请求 Gemini 3.8 Flash (High) 完成补测。旧 Gemini CLI 被服务端拒绝，实际使用入口为 agy。
首轮严格检查 19/24，经过原会话继续执行和 QA 反馈后最终 24/24；全过程与反馈轮次见 [补测报告](gemini-validation-2026-11-04.md)。不要将最终成绩表述为首次无提示全过。

三个独立 Codex 新会话已各执行八案，根协调者运行 scripts/verify_agent_evaluation.py 对文件、台账、ffprobe 和回滚证据复核，24/24 通过。这是规划、恢复决策、配置和文件检查的使用验证，不是 24 次真实视频生产。

不可变输入定义与重放说明：examples/agent-evaluation/。实际记录与轨迹：工作区 production-validation/agent-usage/。精确模型后端未暴露的记录为 unknown，不冒称 Gemini。

result.json 字段：status、decision、evidence（已查看的相对文件路径列表）、next_action、affected_stages、reusable、deliverable、may_continue_b、external_action、issues。轨迹中记录宿主、实际可知模型、开发者提示及限制。
