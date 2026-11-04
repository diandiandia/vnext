# Policy 57 改造测试计划

版本：1.0
适用基线：`f3897ef` 的 policy 57 功能；当前文档基线 `fbe705f`
状态：后续测试工作计划；外部效果评测、正式宿主隔离验收尚未完成

## 1. 目标与决策

本计划指导 policy 57 改造的本地回归、授权真实项目开发试测、独立发现／分诊
比较和宿主隔离验收。先证明实现没有破坏既有合同，再收集真实项目可用性证据；
只有独立效果评估达到预注册标准，才讨论扩大试点或默认启用。

验收对象不是“找出预期漏洞数量”，而是：

1. 既有 Campaign 与默认行为兼容；
2. 新增 workflow 和 safety contract 按定义工作；
3. 失败时显式阻塞、回滚或标注不完整；
4. 可追踪成本、证据来源、计划修订和人工判断；
5. 不把 Agent 声明、测试通过或流程 PASS 误报为真实安全性、隔离或发现效果。

规范需求列表和禁止过度解读的约束见
[Policy 57 改造测试需求](POLICY_57_TEST_REQUIREMENTS.md)。
R0–R6 与常规开发审计规则以 [Skill](../../SKILL.md) 和
[操作手册](../ORCHESTRATOR_RUNBOOK.md) 为准。

## 2. 责任与证据记录

每个测试轮次指定：测试负责人、目标/平台所有者、预算审批者；独立盲评和受保护
标签评估另指定不参与开发的评估者。若同一人承担多个角色，记录并说明独立性限制。

每轮至少保存以下元数据：

```text
run_id
repository and commit (or private evaluator-held identifier)
vNext commit SHA and clean/dirty status
Python/platform/OS/kernel/Agent host/model/provider versions as applicable
task_policy_version and release_policy_version
Campaign constraints, category scope, snapshot digest and state-location policy
test command or live-run procedure
start/end time, wall budget, agent/token/cost measurements and missing fields
result by requirement/test ID: PASS | FAIL | BLOCKED | NOT RUN
failure/skip reason, artifact digests, reviewer and authorized disposition
```
不要把被测项目的秘密、凭证、漏洞答案、私有 patch 或受限评测标签放入公共仓库、
普通 Campaign 或 Agent 可读目录。报告使用获批的去标识化标识。

## 3. 阶段和退出条件

| 阶段 | 目的 | 最低退出条件 | 不可据此关闭 |
|---|---|---|---|
| T0：基线与追踪 | 固定代码、环境、需求、命令 | clean SHA；requirements→test case 追踪完成 | 任一功能／效果接受 |
| T1：定向本地回归 | 验证策略 57 局部合同 | 所有适用 PT57-01…09 通过；外部项明确标 BLOCKED | 真实发现质量、物理隔离 |
| T2：完整兼容回归 | 检查旧生命周期和工具 | 完整 pytest、兼容扫描、Skill/文档检查均通过；所有 skip 有原因 | 未运行的 held-out test |
| T3：真实项目开发试测 | 测试操作可行性、错误和恢复 | 授权/冻结/静态范围；R0–R6、事件、任务和限制完整记录 | CFA-004/030/031 的独立效果验收 |
| T4：隔离宿主验收 | 验证真实动态执行边界 | 指定 OS/Host 的完整策略、正负对抗和失败关闭通过 | 其他平台或 Host 自动通过 |
| T5：独立效果比较 | 比较有无改动的发现与分诊效果 | 事前注册、样本和答案隔离、预算相当、盲评、独立报告 | 未被试验覆盖的语言／项目规模 |
| T6：启用决定 | 决定继续可选试点或申请默认启用 | T1/T2 PASS，且相关外部 gate 有授权结果和独立审批 | 用本地单测替代效果／组织批准 |

任一阶段发现安全边界缺陷，停止受影响的真实测试；保留证据和状态，不继续以
移除限制、跳过 gate 或更换 Campaign 的方式“做完流程”。

## 4. 具体执行批次

### PT57-01：变更基线、Campaign 兼容和 Skill 解析

**范围：** PR57-COMP-01、PR57-SKILL-01、PR57-ID-01。

```bash
git rev-parse HEAD
git status --short
env -u PYTHONPATH python3 -m pytest \
  tests/test_adoption_cli.py tests/test_cli.py tests/test_cli_launcher.py \
  tests/test_campaign_store.py tests/test_task_recovery.py \
  -o addopts='' -q --tb=short
npx --yes skills add . --list
```

**检查：**

- `init` 的新可选策略显式冻结；同一 Campaign 未指定 flag 时保留旧值；
  显式冲突失败而非静默覆盖。
- 既有无新策略 Campaign 不会出现新 critic/domain/budget 事件。
- Skill CLI 只发现预期 Skill、解析更新后的 description；不将其解释为宿主全兼容。
- task retry、Unicode 路径身份及 tuple 次序行为稳定。

**退出条件：** 命令成功；保留 JSON、exit code、策略／identity 断言。失败不得把
工作区或旧 Campaign 状态自动清理后重试。

### PT57-02：基础集成与全量兼容回归

**范围：** 旧 R0–R6、恢复、报告、CLI、目录分发和遗留残留。

```bash
env -u PYTHONPATH python3 -m pytest tests -o addopts='' -q -rs --tb=short
PYTHONPATH=src python3 -m reachable_audit compatibility-scan
git diff --check
```

记录实际 passed/failed/skipped 数量和每个 skip 的原因为。protected held-out
测试没有授权 manifest 时必须保持 skipped；不得造假 manifest、修改标签或把 skip
算作 pass。

### PT57-03：Coverage Critic 生命周期、输出和失败恢复

**范围：** PR57-CRIT-01…03。

```bash
env -u PYTHONPATH python3 -m pytest \
  tests/test_coverage_critic.py tests/test_execution.py \
  tests/test_batch_workflow.py tests/test_batch_closure.py \
  tests/test_campaign_closure.py -o addopts='' -q --tb=short
```

除现有正负测试外，审阅者需确认：

- 启用 Critic 时 initial 在 R3 之前、final 在 R6/Campaign close 之前有效；
  legacy Campaign 不新增门槛。
- 输入的 Plan/Batch/snapshot/stage refs 均为当前对象；上游 stage revision 变化后
  旧 Critic 不再满足门槛。
- direct API、CLI 与 durable task collection/commit 不存在旁路。
- 声明不同 worker ID 的测试只验 ID 规则；日志不得写成 host-verified independence。
- Critic 提出新增/重审建议不会直接变成 Finding；无提案也不得写“无盲区”。

### PT57-04：版本化扩展和显式驳回

**范围：** PR57-PLAN-01…03。

验证 request exact schema、当前 Plan、LOC 锚点、inventory confinement、路径扩展、
boundary/Handoff、重审 Work Unit、幂等、活动任务阻止、旧 Batch supersession、
全 Batch replay，以及数据库中途失败时的原子回滚。

故障注入至少检查 PLAN_RECORDED、batch creation/transition、
BATCH_SUPERSEDED 和 extension marker 的组合状态；数据库回滚后，残存的内容寻址
孤儿 artifact/导出不得被识别为 active Plan。

驳回测试须覆盖每个 proposal 恰好一次、proposal digest 绑定、非 critic 操作者、
源码依据和保留原始输出。任何 defer/reject 缺少依据都不得清除阻塞。

**通过标准：** 新 Plan 身份唯一；旧证据可读但不作为新批结论复用；无法处理的请求
以错误明确失败。成本、全批重放耗时另行报告，不能由单测声称廉价。

### PT57-05：领域选择、知识冻结和边界漏标

**范围：** PR57-DOM-01…02。

```bash
env -u PYTHONPATH python3 -m pytest \
  tests/test_domain_guidance.py tests/test_coverage_critic.py \
  tests/test_execution.py tests/test_knowledge_catalog.py \
  -o addopts='' -q --tb=short
```

对 `ai_agent`、`data_lifecycle`、`supply_chain` 分别用正例和反例检查：
选择 evidence 是否确实锚定当前 Work Unit；未选择是否 NOT ASSESSED；领域指导的
counterevidence 是否进入任务输入；R2 前补选是否影响新的 task revision，R2 后是否
要求新版本 Plan/重新调度。检查 digest 变化、单元／总量上限和 bundle 多单元路径。

单测不证明选择者找到全部适用边界。T3/T5 必须额外记录“未选择域”和后续发现情况，
不可把事后补标签改写成初始覆盖成功。

### PT57-06：未决项投影及严重度隔离

**范围：** PR57-REV-01…02。

```bash
env -u PYTHONPATH python3 -m pytest \
  tests/test_review_delivery.py tests/test_deferred_review.py \
  tests/test_campaign_closure.py -o addopts='' -q --tb=short
```

检查 schema 负例、必需字段、P0/P1/P2/P3/NOT_ASSESSED、JSON/Markdown 一致性、
refs 改变后旧交付不复用、老 Campaign 缺记录显示 NOT_RECORDED，以及原始 R2/R3/
R3.5 stage artifact 未被覆盖。

内容评审必须确认 urgency 文案没有伪装成 CVSS/漏洞严重度，也没有用攻击影响猜测
替代具体 blocker 和可执行计划。

### PT57-07：预算并发、重启和保留额度

**范围：** PR57-BUD-01…03。

```bash
env -u PYTHONPATH python3 -m pytest \
  tests/test_task_budget.py tests/test_execution.py \
  tests/test_campaign_store.py tests/test_adoption_cli.py \
  -o addopts='' -q --tb=short
```

重点检查并发 connections、BEGIN/事务边界、每 attempt reservation、失败／重试、
过期 lease、缺测量、重复报告、重启、扩额单调性和 protected downstream admission。
验证 token、wall time、agent run、delegation、cost 等有配置的维度分别记账，不混单位。

**通过标准：** 不 oversell、不把缺失测量作为免费额度、不因报告 invalid 或失败
而抹除已发生消耗；余额不足时显示具体阻止原因。所有成本字段需区分估算、已报告
值和缺测量。Provider hard cap 是 BLOCKED，除非另有真实 Provider 证据。

### PT57-08：产物转存对抗测试

**范围：** PR57-HOST-01、03。仅在当前 OS／文件系统支持的测试环境运行。

```bash
env -u PYTHONPATH python3 -m pytest \
  tests/test_safe_artifacts.py tests/test_harness_runner.py \
  tests/test_go_harness_runner.py -o addopts='' -q --tb=short
```

覆盖父级／叶级 symlink、FIFO、硬链接、非 allowlist 路径、路径穿越、逐文件／总量
超限、复制期间源增长、目标冲突、失败部分目标清理、文件描述符继承、stdout/stderr
捕获及写入者仍活动时的拒绝／阻塞前提。记录底层 OS、文件系统和权限。

Windows 或缺少 no-follow/dirfd 语义的平台必须显式 BLOCKED/unsupported，不以
`shutil.copy` 等未验证降级方式通过。

### PT57-09：Host 隔离 fail-closed 检查

**范围：** PR57-HOST-02、QUAL-02。

本机 `bwrap` 曾因无权创建 namespace 而不可用；该环境仅验证失败关闭，不构成
隔离验收。确认 `host-capabilities` 标明可用性和原因，且 `target_execution_attempted`
为 false。`harness-run --isolation linux-bwrap` 在缺能力／策略时须先失败，目标命令、
构建、文件写入及经验确认事件均不得发生。

真实正向隔离验证须由授权宿主负责人单独安排，先批准完整策略与靶场；至少验证：
网络、环境变量、凭证、源树／保留区写访问、子进程树、CPU/内存/时间、输出大小、
异常退出、捕获、清理及可重启性。隔离缺能力时结果为 NEEDS_REVIEW/NOT_FEASIBLE，
不得为获取证据移除 isolation flag。

### PT57-10：真实项目开发试测（非盲测）

仅针对已授权、固定 commit 的真实项目，且使用新的 `fresh` Campaign。建议选取一个
规模可控、边界可理解的项目；避免从旧审计的已知漏洞开始，也不把其预期发现交给
worker。state directory 放在源码之外。记录范围与排除项，使用 `--static-only`，
除非宿主已通过 PT57-09 正式验收。

建议分开跑四个 arms（同一冻结快照的独立 Campaign）：

1. baseline：policy 57 可选策略不启用；
2. critic-only；
3. domain-guidance-only；
4. critic + domain-guidance。

先单独验证运行可恢复、事件完整、目录／证据锚点有效和未决项展示。记录人工后来
发现的未检边界与误导指导，作为开发反馈而不是 ground truth。Campaign PASS、
proposal 数、hypothesis 数都不是效果指标。

运行前预估 versioned extension 的全批重放成本和预算；预算不足应先缩小获批范围或
停止，不能在运行中偷偷抽样。尽量使用独立 coordinator/worker context，且报告这一
隔离只是宿主操作事实，除非有客观 host proof。

### PT57-11：独立发现与分诊效果比较（外部阻塞项）

依据[发现质量评估协议](DISCOVERY_QUALITY_EVALUATION_PROTOCOL.md)执行。测试前由
独立评估者冻结：样本/根因标签、scope、模型与 Host、随机化/配对顺序、预算、候选匹配
标准、样本量和停止条件、主要指标及可接受成本／误报阈值。标签、fix diff 和答案必须
对 Campaign 与 worker 不可见；保留未参与调参的 holdout。

按语言和机制分别报告：

- 有效、带源码证据的根因候选召回；不是 Hypothesis 数或 prompt keyword 命中；
- 经过盲评的错误候选负担、结论一致率和审阅时间；
- Critic 提出有效遗漏、无效扩展和重复建议的比例；
- 领域指导被正确选择、错误选择和漏选的情况；
- token／agent runs／wall time／费用；报告缺测与不确定区间；
- 所有 scope omission、任务失败、预算阻断和重试均保留在分母。

如果独立评估者、样本或标签隔离缺失，标记 **BLOCKED**。不得用 QuickJS/Tomcat
等已知目标计划或旧项目结果充当 holdout，也不得在看到结果后补定阈值。

### PT57-12：文档／Skill 可发现性和合同一致性

```bash
npx --yes skills add . --list
npx --yes skills add diandiandia/vnext --list
git diff --check
```

检查描述与 README、Skill、runbook 一致；README 明确 Skill 安装与 runtime 启动
的区别；政策与限制没有被包装为已验证发现质量或宿主兼容。版本号、命令和 JSON
contract 必须对应代码。

## 5. 总体完成标准

可宣布“本地实现回归完成”必须同时满足：

1. PT57-01…08、PT57-12 在目标平台通过；所有 FAIL 已修复或接受为明确阻塞，
   并有 issue/责任人/复验条件。
2. 全套 tests 与 compatibility scan 通过；skip 已逐项说明，不伪装通过。
3. 在受支持主机上复核 transaction、身份、replay 和 report 行为。
4. 测试工件及需求追踪已归档；无敏感目标细节泄漏。

只有 PT57-09 的主机正向证据通过后，才能对对应 Host/OS 宣称隔离测试通过。
只有 PT57-11 独立研究通过后，才能对覆盖效果或默认启用提出结论。任一项都不能
由本地单测、文档自评或 Google/ISO 名称推导出来。

## 6. 结果记录模板

```text
Test run ID:
vNext commit / dirty state:
Platform / Host / Agent / model:
Task policy / release policy:
Campaign mode / constraints / source snapshot digest:
Test phase and requirement IDs:
Command or approved procedure:
Results: PASS / FAIL / BLOCKED / NOT RUN
Pass/fail/skip counts and reasons:
Token / agent-run / wall-time / cost (reported vs missing):
Artifacts and digests:
Observed deviation / issue:
Reviewer / approval / next action:
Claims explicitly not made:
```
