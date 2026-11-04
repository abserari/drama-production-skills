---
name: comfy-h3-video-producer
description: 执行本地 H3 视频制作路径，完成工作流握手、分镜提交、监工和受检收片；多工序项目先使用 drama-production-director。
---
# H3 制作路径
## 适用与输入
用于已选 H3 路径的项目。先读 project.json、plan.json、progress.json，确认服务、模型、工作流、首帧要求及声音模式。纯文本或已有素材无需进入本技能。
## SOP
1. 按实际服务配置 H3_COMFY、H3_INPUT_DIR、H3_OUTPUT_DIR、H3_PROJECT_DIR，禁止照抄旧机器路径。
2. scripts/h3wf.py sync/show/doctor 握手；缺 CSGlide 等节点时报告不兼容，不凭节点号改图。
3. 用 scripts/sop_run.py submit/watch/final 执行，实际参数以 --help 为准。提交结果不明先核对台账和 queue/history。
4. scripts/h3proj.py gate/review/finish/concat 执行检查、复核、收片。调用前逐项核验 plan 的必需输入。I2V 首帧不可缺失或损坏。
5. 调用独立审查技能保存证据，全部必需项通过才交付。
## 输出与证据
项目内视频、实际提交与任务编号、输入指纹、检查报告和产物哈希。视频存在、返回零、文件够大均不证明内容合格。
## 恢复与替换
暂态最多重试两次、质量最多返工两轮。结果未知不得重投，关键模块异常必须修复。总协调者是台账唯一写入者。
## 参考与约束
旧工具细节按需查 references/legacy-production-manual.md；该文是历史机制参考，其旧路径、固定时长、强制凝视、速度及效果数字均不是当前通用要求。语速、运镜、段尾动作由项目决定。当前安装只支持真实存在的节点；切换工具另选技能，不伪造兼容性。
