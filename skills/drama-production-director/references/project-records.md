# 项目记录与交接

项目目录是状态真相来源。模板是新增字段示例，不是要求把旧格式全部重写。保留旧字段，新增 `schema_version` 和 `production`；旧工具只认识的字段继续保留。所有相对素材路径以项目目录为基准，调用工具时解析为绝对路径。

- `project.json`：项目 id、目标、所选路径、制作配置、技能版本、审查策略；不得写凭据。
- `plan.json`：`stages` 的 id、skill、depends_on、inputs、outputs、required、acceptance；视频项目沿用 `segs`。没有视频就不创建空分镜或虚假首帧。
- `progress.json`：沿用 `segs`，通用工序放 `stages`。每项记录 status、attempts、external_job_id、input_fingerprint、artifact、checks、next_action。
- `checks/`：程序检查、agent/人工审查、迁移冲突和返工记录。
- `artifacts/`：新产物；既有项目允许继续使用 segments、cleaned_segments、成片等目录，不搬动历史媒体。

状态使用 `pending / running / needs_review / passed / failed / blocked / cancelled`。未知外部回执用 `blocked` 加 `next_action: reconcile_external_job`；不要填 passed。执行脚本有旧状态时保存原始状态，并由协调者映射，不直接篡改旧工具字段。

产物证据至少包括 path、sha256、大小、检查时间；视频再记录解码、时长、画幅、音轨。依赖指纹覆盖实际输入内容、最终提示词、参数、工作流及影响输出的技能版本。混音参数变化只使混音及交付失效，不使视频生成失效。

对机器可读记录使用现有原子写入辅助函数。子 agent 不写总台账；返回 `{stage_id, status, outputs, checks, issues, next_action}`。原子替换避免半写，不能代替单写入者规则。

审查记录采用 review 技能的模板。机器签名表示检查执行者，不表示人类授权；人工来源记录用户消息或评审文件引用，不伪造证明。

旧项目导入：复制计划与描述到新目录，媒体用来源路径引用；比较根目录和生产目录两份计划。冲突写入 checks/import-conflicts.json，并阻塞受影响工序。历史视频只标记 imported_unverified；媒体解码成功也不代表剧情合格。重复导入按源路径+哈希识别，不能重复登记。


## 已有 H3 工具的可执行约定
- 渲染身份字段：project 的 selected_skills、render_settings、visual_style_version、production_path、requires_keyframe。混音配置放 mixing，不放 render_settings，避免误使渲染失效。
- plan.required_reviews 可列 `{stage_id, mode:"blocking", review_path, artifact_path, reviewer_kind}`；收片检查 stage_id=分镜 id，拼接检查 stage_id=concat，`*` 表示全部。路径以项目为基准。未配置的人工定调仍由总协调 SOP 执行，不冒称程序自动核验全部创作判断。
- 如果终片与一采不是同一文件内容，先观察终片，再执行 h3proj.py review --seg ID --video ABS_PATH --pass --evidence ABS_EVIDENCE；该命令记为 agent 审查，人工结论另存真实用户来源。
- concat 产物状态 needs_review；拼接技术成功后仍须执行全片审查，不能立即宣布交付。
