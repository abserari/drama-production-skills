# 按需技能目录

| 职责 | 技能 | 何时读取 |
|---|---|---|
| 总协调 | drama-production-director | 多工序、恢复、替换、交付判断 |
| 故事创作 | short-drama-writing（外部技能） | 大纲、人物、分集、剧本改写 |
| 导演分镜 | drama-director-staging | 把剧情变成可制作镜头 |
| H3 提示词 | h3-prompt-writing（外部技能） | 按具体模式编写提示词 |
| 资产与首帧 | drama-keyframe-forge | 确实需要建立视觉资产或所选路径要求首帧 |
| H3 路径手册 | comfy-h3-video-producer | 既有导演台工作流握手、提交、收片 |
| H3 渲染 | comfy-h3-render-core | 物理参数、显存、任务恢复 |
| 声音 | drama-audio-soundstage | 台词检查、降噪、配乐和混音 |
| 交付 | drama-finishing-upscaler | 拼接、可选超分、参数验收 |
| 独立审查 | drama-production-review | 任意工序检查、抽验或已有项目验收 |

外部技能按宿主的技能目录发现。本机已提供 short-drama-writing 与 h3-prompt-writing；发布到别处时先确认可用，不声称本包已携带。缺失时可由 agent 按明确的项目交接要求完成该工序，记录替代方法；模型特定格式无法确认则阻塞该路径，不编造接口。

工具仅为技能内部实现；不存在统一 drama 命令或 MCP 服务。用各技能实际列出的脚本，调用前看 --help。旧十集母调度属于特定项目工具，不是通用入口。
