# 项目改造路线：从 FRU 工具到故障诊断研究原型

## 当前问题

当前代码保留了较多 `fru` 命名，例如 `fru_diagnosis`、`FRUModule`、`fru_id`。这些命名适合维修视角，但论文主线应转向软件层故障诊断。为了不破坏现有仪表盘和脚本，短期不做大规模重命名，而是采用“故障诊断入口 + FRU 兼容层”的方式演进。

## 目标结构

建议长期演进为：

```text
fault_diagnosis/
  evidence_schema.py
  fault_taxonomy.py
  diagnosis_engine.py
  evidence_fusion.py
  active_diagnosis.py
  crash_diagnosis.py
  serviceability.py
  datasets/

fru_diagnosis/
  # 兼容旧仪表盘、旧配置和旧命令
```

其中：

- `fault_diagnosis` 面向论文叙事，表达故障来源、证据融合和主动诊断。
- `fru_diagnosis` 面向现有工程兼容，继续支撑设备配置、仪表盘和历史测试。
- FRU 逻辑下沉到 `serviceability.py`，作为维修决策输出。

## 推荐修改顺序

1. 新增 `fault_diagnosis` 入口包，重新导出研究相关能力。
2. 新增故障分类 taxonomy，统一 software、driver、OS、firmware、configuration、environment、hardware、unknown 等类型。
3. 把数据集 Label 中的 `serviceability_type` 保留，但新增或强化 `fault_origin`、`root_cause_type`、`final_root_cause`。
4. 把实验脚本描述从 “FRU diagnosis cases” 改为 “fault diagnosis cases”。
5. 仪表盘中把“FRU 候选”改为“诊断候选”，FRU/Non-FRU 只作为候选类型显示。
6. 后续再逐步把变量名 `fru_id` 泛化为 `candidate_id`，避免一次性破坏接口。

## 论文版本的模块边界

### 证据层

输入：

- device_id
- fault_case_id
- timestamp
- fault_time
- symptom
- inventory
- logs
- metrics
- active_tests
- crash_dump
- repair_result
- final_root_cause

输出：

- 标准化 DatasetCase
- 可复现实验 JSONL

### 知识层

输入：

- symptom ontology
- software/hardware fault ontology
- OS-specific rules
- BSOD rules

输出：

- 候选根因空间
- 证据与候选之间的映射

### 推理层

输入：

- 标准化证据
- 候选根因
- 本体和规则

输出：

- candidate
- fault_origin
- belief
- uncertainty
- supporting_evidence
- conflicting_evidence
- next_best_test

### 主动诊断层

目标：

在证据不足时，不只提示“缺少证据”，而是根据收益、成本和风险推荐下一步测试。

示例：

- BSOD：collect_minidump
- 充电异常：collect_power_acpi_ucsi
- 网络异常：gateway_ping_and_driver_check
- 黑屏：external_display_test
- 启动失败：storage_health_and_short_test

### 维修决策层

输出：

- 软件修复
- 驱动回滚/更新
- 系统修复
- 固件升级
- 配置恢复
- 环境复测
- 硬件更换
- 继续采集证据

## 保留当前版本的原则

- 不删除 `fru_diagnosis`。
- 不修改现有数据文件语义。
- 不破坏仪表盘 payload。
- 新研究能力优先通过新增模块、文档和实验脚本接入。
- 等实验数据稳定后，再进行命名层面的系统性迁移。

