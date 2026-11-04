# Gemini 独立使用补测（2026-11-04）

## 实际入口
- 旧 @google/gemini-cli 0.66.0 返回 UNSUPPORTED_CLIENT：个人版服务要求迁移到 Antigravity，并非简单重复登录能解决。
- 本机 Antigravity CLI（agy 1.2.0）可用。通过 --model 显式请求 gemini-3.8-flash-high，工具目录列出该模型，READY 探针成功。
- 隔离模式尝试遇到独立登录环境缺失，已停止、保留证据且不计通过。正式补测使用普通本机模式，限定任务目录和技能读取范围。

## 实验与结果
三个新会话各执行八案，随后在原 conversation_id 下继续完成遗留项，没有用 Codex 代写 Gemini 产物。

|阶段|案例检查通过|含义|
|---|---|---|
|首轮初步文件检查|20/24|当时还未覆盖审查 SHA 绑定|
|首轮完整检查|19/24|补充核对计划 outputs 与当前审查哈希后的严格结果|
|继续执行及质量反馈后|24/24|有反馈的最终结果，不是无提示首次全过|

首轮发现：两组缺少第八案结果；一组复制模板的 outputs 与实际规划文件不一致；一组缺少必需审查文件；一组审查没有绑定当前产物 SHA256。首轮原始目录保存在 first-pass-evidence，未覆盖为最终状态。

修正措施：
1. 总协调技能明确按实际交付范围调整模板，并逐项核对 required outputs、当前哈希与审查文件，缺项不能标 passed。
2. 审查技能明确不接受制作方自报通过。
3. 检查器根据 plan 声明的实际路径检查，允许合法的根目录 planning.md，不强制 artifacts 文件夹；同时检查审查文件存在、passed、证据与当前 SHA256。
4. 三个原会话收到一次程序性继续执行反馈；run-3 额外收到一次明确的哈希 QA 反馈，run-1 额外补齐原先要求的轨迹文件。提示及轮次全部保留。

最终实际核对：24 个 result.json、三个 trace-notes.md 均存在；纯文字规划真实落盘；缺首帧/坏文件/缺镜不能交付；b 状态未被 a 的风格改变；恢复保留原任务编号；回滚恢复 baseline-v1 并保留候选及失败证据。

## 证据与复现
工作区 production-validation/gemini-ready/：
- auth-verification.json：入口及认证探针。
- evaluator.json、host-response.json / continuation-response.json / QA 响应：显式模型请求、会话 id、执行轮次。
- first-pass-evidence/、first-pass-verification.json、first-pass-strict-verification.json：首轮记录。
- verified-results.json：最终文件与台账核对。
- run-*/trace-notes.md：Gemini 自己记录的动作、限制及反馈。
- host-usage-reported.json：CLI 报告的累计会话耗时和 token 数据；没有推断货币成本，也没有重复相加同一会话的多轮累计值。

新输入定义仍在 examples/agent-evaluation/input-cases.json；准备新目录使用 scripts/prepare_agent_evaluation.py；核对使用 scripts/verify_agent_evaluation.py。旧 Codex 24 案独立保留在 production-validation/agent-usage。

## 结论边界
Gemini 能读取这些技能并完成本批规划、配置、恢复决策与文件验收案例；独立检查捕获了它的漏项并驱动修复。这批结果支持“agent 决策 + SOP + 少量确定性检查”的架构。

本实验有反馈补齐，不能宣传为首次无干预通过；不是 24 次真实媒体生成，不证明台词、口型、审美或任意新剧本无人值守合格，也不构成统计模型优劣排名。首轮 CLI 返回 SUCCESS 仍有缺项，说明退出码不能代替产物验收。
