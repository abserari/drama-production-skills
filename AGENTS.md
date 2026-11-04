# AGENTS.md

> **AI 代理与工程维护常驻契约 (Standing Covenant for Agents & Maintainers)**  
> 本文件为所有在 `drama-production-skills` 仓库工作的 AI 代理（包括 Antigravity、Claude、DeepSeek 等）和人类维护者提供常驻治理规范、架构红线与维护 SOP。

---

## 一、 项目定位与愿景

`drama-production-skills` 是基于 MiniMax H3 多模态视音频生成模型（AV-DiT）与 ComfyUI 的**工业级短剧多工序制作流水线与技能矩阵**。本仓库不绑定特定单一剧本，而是沉淀跨项目通用、换剧本依然成立的标准化技能、工具链、断场考题库与架构决策。

---

## 二、 唯一的真实来源 (Sources of Truth)

在对本仓库进行任何代码阅读、设计判断或修改前，必须优先阅读以下基准文档：

1. **核心架构决策记录 (ADR)**：[`docs/evolution-and-decisions.md`](docs/evolution-and-decisions.md)
   - 规定了为什么放弃纯 TTS 回归原生音轨（ADR-01）、为什么续接只传状态不传叙事（ADR-02）、为什么建立五级闸门与金样本考题库（ADR-03）、台词前置时序铁律（ADR-04）、算力边界与禁止减步数（ADR-05）、多工序解耦标准（ADR-06）。
2. **代理评测与工程状态**：[`docs/agent-evaluation.md`](docs/agent-evaluation.md) 与 [`docs/implementation-status.md`](docs/implementation-status.md)
3. **官方原始英文规范与指南**：`skills/comfy-h3-video-producer/references/official/` (`base-en.txt`, `ref-en.txt`)
4. **历史全量规约参考**：`skills/comfy-h3-video-producer/references/original-v3.10.2-manual.md`

---

## 三、 仓库目录布局 (Repository Layout)

```
drama-production-skills/
├── AGENTS.md                                # 顶层契约（本文件）
├── .agents/
│   └── skills/                              # 代理发现技能库（统一技能入口）
│       ├── drama-pre-push-checks/           # 仓库治理：本地最小充分性验证门禁
│       ├── drama-doc-standard/              # 仓库治理：文档规范与实证原则
│       ├── drama-code-review/               # 仓库治理：PR 与架构合规审查
│       ├── comfy-h3-render-core/            # 生产工序：H3 物理渲染执行
│       ├── comfy-h3-video-producer/         # 生产工序：单技能兼容直通路径
│       ├── drama-audio-soundstage/          # 生产工序：音频声场与侧链压限
│       ├── drama-director-staging/          # 生产工序：导演分镜与节拍编排
│       ├── drama-finishing-upscaler/        # 生产工序：后期拼接与 4K 超分
│       ├── drama-keyframe-forge/            # 生产工序：首帧与视觉资产锚定
│       ├── drama-production-director/       # 生产工序：总制片与协调调度
│       └── drama-production-review/         # 生产工序：全流程质检与独立验收
├── skills/                                  # 规范源码技能库（与 .agents/skills 保持同步）
├── docs/                                    # 系统级架构文档、决策记录 (ADR)、独立审计报告
├── scripts/                                 # 跨工序通用工具链（混音、超分、门禁、技能发布）
├── tests/                                   # 自动化单元测试与回归套件（pytest）
├── examples/                                # 历史项目脱敏数据、评估用例、技能替换示例
└── workflows/                               # ComfyUI 核心 API 工作流 JSON 模版
```

---

## 四、 不可逾越的工程红线 (Non-Negotiable Invariants)

所有 Agent 在进行功能开发、重构或 Bug 修复时，必须严格遵守以下 6 条红线。**任何违反红线的 PR 或修改一律视为阻断性错误：**

1. **红线 1：严禁减采样步数提速 (ADR-05)**
   - 严禁将生成步数从 20 步减到 10 步，亦不得引入未经验证的激进画面缓存；采样步数减少会导致高频音频信号严重失真破碎。
2. **红线 2：台词必须排在第一拍最前 (ADR-04)**
   - 提示词文本中，`<Audio N>...说：<d>...</d>` 必须紧随 `<Subject>` 置于文本最前端，动作描写整块后置于 `<d>` 标签之后。动作排在台词前会导致台词被顶到段末甚至直接吞字。
3. **红线 3：续接只传状态，不传叙事 (ADR-02)**
   - 续接段每段第一拍必须直接写新镜头（新机位/新动作），严禁在提示词中要求开头延续上一段数秒动作；通过 `concat` 读取台账 `cont.frames` 自动裁去 5 帧钉帧。
4. **红线 4：严禁硬编码宿主机物理路径**
   - 任何 Python 代码或文档指令中，不得出现 `D:/...`、`C:/Users/...`、`/home/...` 等硬编码路径；必须统一通过 `paths.py` 或环境变量（`COMFYUI_PATH`, `H3_COMFY`, `H3_ASR_PY`, `H3_OUTPUT_DIR`）动态跨平台探测。
5. **红线 5：严禁将项目业务私货写入公共技能库**
   - 特定短剧的剧本、特定角色提示词或大体积未脱敏媒体，一律归入具体项目工作区或 `examples/`，严禁污染公共技能；公共技能仅沉淀跨剧本通用的机制与判据。
6. **红线 6：证据交付闭环原则**
   - 任务完成的唯一判定标准是“存在真实的验证证据”（如 `pytest` 40 项全绿、`pre_push_check.py` 退出码为 0）。严禁在未经实际运行的情况下声称已验证。

---

## 五、 如何维护这个仓库 (Maintenance Guide)

### 1. 修改或新增一个技能 (Skill SOP)
- **遵循渐进式披露 (Progressive Disclosure)**：
  - `SKILL.md` 保持简短精炼（严格控制在 100 行内），仅包含 YAML 前置元数据、调用触发时机、简要 SOP 和阻塞性检查点；
  - 详尽的理论模型、参数对照表、排错指南一律拆入该技能下的 `references/<topic>.md`；
  - 技能私有工具放入该技能下的 `scripts/`。
- **双向同步**：
  - 在 `skills/` 或 `.agents/skills/` 中做出的变更，必须通过同步脚本保证两边一致：
    ```bash
    python scripts/sync_skills.py --target .agents/skills --apply
    ```

### 2. 本地质检与推送门禁 (Pre-Push Quality Gate)
在任何 `git commit` 或 `git push` 前，必须运行本地自动化预检脚本：
```bash
python .agents/skills/drama-pre-push-checks/scripts/pre_push_check.py
```
该脚本自动执行以下四大门禁：
1. **工作区卫生**：确保无未被 gitignore 的临时垃圾文件（`.tmp`, `.log`, `.bak`）或超大媒体；
2. **单元测试**：执行 `pytest tests/`，必须 100% 通过；
3. **路径安全性**：静态扫描活跃代码中是否引入了硬编码机器路径；
4. **断场回归 (Golden Regression)**：调用 `golden.py` 验证 16 个断场案例零退化。

### 3. 重大架构与决策沉淀 (ADR SOP)
当改动涉及底层生成逻辑、重要默认参数修改、主备路径切换或新工序引入时：
1. 必须在本地或真实工程中完成实测比对；
2. 依据事实将决策背景、对比数据、结论与放弃的备选方案以 ADR 格式追加到 [`docs/evolution-and-decisions.md`](docs/evolution-and-decisions.md)；
3. 同步更新相关的 `references/` 文档与测试用例。

### 4. 代码审查标准 (Code Review)
Review 任何 PR 或 Diff 时，调用 `.agents/skills/drama-code-review/`，严格对照其 [review-checklist.md](.agents/skills/drama-code-review/references/review-checklist.md) 逐项排查。
