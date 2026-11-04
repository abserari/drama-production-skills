# 文档层级与治理规范 (Doc Hierarchy & Governance)

本文档定义 `drama-production-skills` 仓库的文档分层结构与编写规范，参考 `deepseek-harness`（`dsh-doc`）的渐进式披露（Progressive Disclosure）与事实唯一性标准。

---

## 一、 文档四层架构

```
drama-production-skills/
├── AGENTS.md                                # Level 1: 顶层常驻契约（面向所有 Agent 与人类协作者）
├── docs/                                    # Level 2: 跨工序全景与决策中枢
│   ├── evolution-and-decisions.md           # 架构决策记录 (ADR) 与演进史
│   ├── agent-evaluation.md                  # 代理评测基准与独立验收
│   └── ...                                  # 架构全景与安全审计
├── skills/<skill-name>/                     # Level 3: 工序级专业知识库
│   ├── SKILL.md                             # 简明调度契约（< 100 行，轻量入口）
│   └── references/                          # 细分专业规约（深层知识，按需读取）
└── examples/ & tests/                       # Level 4: 活文档与脱敏示例（代码即文档）
```

---

## 二、 核心编写铁律

### 1. 事实检验原则 (Fact-Check Procedure: Test, Do Not Assume)
- **文档仅陈述代码当前的真实行为**。
- 严禁凭记忆、旧版印象或外部工具类比编写命令行或配置；
- 文档中给出的任何 CLI 指令、JSON 字段名或环境变量，**作者必须在本地环境实际运行成功后方可写入**；
- 凡是未通过验证或由于环境缺少而无法复现的指令，必须在文档中明确标注前提条件或直接剔除。

### 2. 渐进式披露原则 (Progressive Disclosure)
- **严禁单一 `SKILL.md` 巨石化**：单技能主文件 `SKILL.md` 严格控制在 100 行以内，只包含：
  1. YAML 前置元数据（`name`, `description`，重点说明何时使用此技能）；
  2. 简明核心 SOP 步骤；
  3. 阻塞性检查点与输入输出协议；
  4. 指向 `references/` 的链接。
- 所有超过 100 行的操作手册、踩坑复盘、理论模型、详细参数表，一律拆分至对应技能的 `references/<topic>.md`，避免 Agent 在多轮对话中因加载巨型文档导致上下文溢出。

### 3. 重大决策落入 ADR (Architecture Decision Record)
- 涉及工作流底层改动、AI 提示词语法调整、模型阈值变更、主备生产路径切换的任何决策，必须以 ADR 格式追加到 `docs/evolution-and-decisions.md` 中，包含：
  - **背景 (Context)**；
  - **实测证据 (Evidence & Data)**；
  - **决策结论 (Decision & Invariants)**；
  - **放弃的备选方案及其缺陷 (Rejected Alternatives)**。
