> 合并适配：本文保留同事资料与原案例。其“实测/硬约束”仅代表原环境；当前项目以本技能入口及 [合并说明](../merge-notes-20261107.md) 为准。情绪/运镜菜单按镜选用，不强制每句加微笑、预备动作、走动或固定停顿。

# directing/ —— 导演调度资料库（原 `director-advisor` 技能，2026-11-06 并入）

> 原 `director-advisor` 技能已退役删除，其独有资料整体迁入本目录，
> **职能并入本技能 §3（导演调度）**，不再依赖外部技能。

| 文件 | 用途 |
|---|---|
| `master_cases.md` | **大师案例锚库**：按场景类型（争吵/追逐/暧昧/告别/孤独/权力/闪回…）挂真实电影案例；引用铁律=只引用库内片名，一次最多挂 2 个 |
| `shot_grammar.md` | **镜头语法**：景别=情绪距离 / 运镜=情绪运动 / 角度=权力关系 / 构图=心理暗示 / 光线=情绪基调（物理写法）/ 四个合法切点 / 听者优先 |
| `beat_rhythm.md` | **戏剧节拍→分镜节奏**：单场五要素、节拍类型→分镜参数表、张力曲线（最高点只有一个）、对话戏/动作戏专项、AI 适配硬约束 |
| `director_advisor_skill_archive.md` | 原 director-advisor SKILL.md 存档：五变量拆解工作流、分镜方案输出格式、**`shots-json` 机读块节**（`scripts/storyboard_json.py` 仍按它解析） |

使用入口：SKILL.md §3（导演调度）→ 出分镜方案（机读块用 `storyboard_json.py` 抽取）→
`references/directing_bridge.md` 换算成 H3 段。
