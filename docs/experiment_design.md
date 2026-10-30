# 软硬件边界故障诊断实验方案

## 数据使用原则

正式实验只能引用 `datasets/source_registry.json` 中 `canonical_datasets`
登记的数据版本。未登记的临时目录、旧版本和下载缓存不能用于论文结果。

当前保留三个规范数据集：

| 数据集 | 作用 | 允许支持的结论 |
|---|---|---|
| `diagnosis_v3_loghub2k` | 软件日志基线 | 日志解析、软件侧弱标签实验 |
| `diagnosis_v7_rcaeval_re2` | 正式主实验 | 多源软件服务根因定位 |
| `diagnosis_v8_rcaeval_re2_re3` | 补充实验 | 跨版本鲁棒性分析 |

上述数据均不能单独支持硬件端点、接口路径、FRU 更换或维修准确率结论。

## 当前正式流程

RCAEval 主实验：

```powershell
py -3.14 experiments\run_rcaeval_formal_experiment.py `
  --dataset-dir datasets\processed\diagnosis_v7_rcaeval_re2
```

数据完整性验证：

```powershell
py -3.14 scripts\validate_diagnosis_dataset.py `
  datasets\processed\diagnosis_v7_rcaeval_re2
```

软件日志基线：

```powershell
py -3.14 experiments\run_baselines.py `
  datasets\processed\diagnosis_v3_loghub2k\test.jsonl `
  reports\experiments\diagnosis_v3_loghub2k\test_graph_fusion.jsonl `
  --method graph_fusion
```

## 下一阶段：边界数据集

新的边界数据集必须包含以下真值类别：

- `software_side`
- `firmware_control`
- `interface_path`
- `hardware_endpoint`
- `external_environment`
- `no_fault_observed`

其中 `interface_path` 和 `hardware_endpoint` 样本必须具有独立于日志的确认信息，
例如主动测试、SMART/WHEA、设备枚举异常、接口链路状态或维修复测结果。

建议原始目录：

```text
datasets/raw/local_cases/
  <case-id>.jsonl

datasets/raw/backblaze/
  *.csv

datasets/raw/openrepair/
  *.csv
```

构建命令：

```powershell
py -3.14 scripts\build_diagnosis_dataset.py `
  --version diagnosis_boundary_v1 `
  --sources backblaze openrepair local_cases
```

边界正式门禁：

```powershell
py -3.14 scripts\validate_diagnosis_dataset.py `
  datasets\processed\diagnosis_boundary_v1 `
  --profile boundary
```

未通过该门禁的数据只能用于开发或软件侧实验，不能进入边界主结果。

## 划分要求

- 同一设备、故障案例和维修闭环不得跨越 train/dev/test。
- 主测试集优先使用 gold/silver 标签。
- weak 标签只能用于预训练、消融或单独报告。
- 测试集必须覆盖软件侧、接口路径和硬件端点。
- RE2 与 RE3 的故障类型定义不同，不合并报告统一 fault-type 主指标。

## 核心指标

- Boundary accuracy、Macro-F1、混淆矩阵
- Root-cause Top-1、Top-3、MRR
- Expected Calibration Error
- 缺失模态性能下降
- 不必要硬件更换率
- 主动测试 Hit@1/Hit@3 和信息增益

