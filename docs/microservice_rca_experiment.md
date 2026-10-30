# 微服务系统多源可观测数据融合根因诊断实验

## 研究目标

研究日志、运行指标和调用链三类可观测数据的融合，是否能够提升微服务系统的服务级根因定位和故障类型识别能力。

主问题：

> 时序异构证据融合能否在未见过的服务-故障组合上提升组合根因定位能力？

## 数据与划分

主实验使用 `diagnosis_v7_rcaeval_re2`：

- 270 个注入案例；
- train/dev/test = 162/54/54；
- 故障类型：CPU、内存、磁盘、延迟、丢包、Socket；
- 模态：日志、指标、调用链；
- 按 benchmark、服务和故障类型保持场景组不跨 split。

补充实验使用 `diagnosis_v8_rcaeval_re2_re3`，只用于跨版本鲁棒性，不把 RE2 与 RE3 的 fault type 合并为一个主指标。

数据质量限制：RCAEval 是服务级软件故障注入数据，不支持硬件端点、接口路径、FRU 或维修决策结论。

## 任务定义

对每个案例输出三个层级：

1. 根因服务 `root_cause_service`；
2. 故障类型 `fault_type`；
3. 组合根因 `root_cause = service:fault_type`。

## 对比方法

| 方法 | 使用证据 | 目的 |
|---|---|---|
| `majority_prior` | 无 | 多数类下限 |
| `keyword_heuristic` | 全部文本证据 | 规则下限 |
| `logs_tfidf` | 日志 | 日志单模态 |
| `metrics_tfidf` | 指标 | 指标单模态 |
| `traces_tfidf` | 调用链 | 调用链单模态 |
| `early_fusion_tfidf` | 日志+指标+调用链 | 早期特征融合 |
| `late_fusion_tfidf` | 三模态独立模型 | 后期分数融合 |
| `temporal_signal_fusion` | 指标时间变化+日志/调用链 | 时序规则融合 |
| `temporal_fusion_tfidf` | 时序特征+异构文本 | 当前重点方法 |

## 研究问题与假设

### RQ1：多源融合是否优于单模态？

比较日志、指标、调用链与融合模型的 root Top-1、Top-3 和 Macro-F1。

### RQ2：时序特征是否提升根因定位？

比较 `early_fusion_tfidf` 与 `temporal_fusion_tfidf`，报告故障前后指标变化特征的增益。

### RQ3：服务定位和故障类型识别是否存在不对称收益？

分别报告服务级指标、故障类型指标和组合根因指标，避免只报告一个准确率。

### RQ4：模型能否泛化到未见组合？

根据 `split_label_overlap` 报告测试集中未在训练集出现的组合根因数量，并单独报告这些案例的 Top-K 性能。

### RQ5：跨版本是否稳定？

在 RE2 训练、RE3 测试或 v8 的分层结果上比较性能变化，不合并不同版本的 fault type 标签。

## 评价指标

- `root_accuracy`
- `root_top3_accuracy`
- `root_top5_accuracy`
- `root_macro_f1`
- `root_mrr`
- `service_accuracy`
- `service_top3_accuracy`
- `service_macro_f1`
- `fault_type_accuracy`
- `fault_type_macro_f1`
- 每个 source dataset 和 fault type 的分组指标

主指标建议使用 `root_top3_accuracy`、`root_mrr` 和 `root_macro_f1`；`service_accuracy` 作为辅助指标。

## 运行命令

主实验：

```powershell
py -3.14 experiments\run_rcaeval_formal_experiment.py `
  --dataset-dir datasets\processed\diagnosis_v7_rcaeval_re2 `
  --output-dir reports\experiments\diagnosis_v7_rcaeval_re2_formal
```

补充实验：

```powershell
py -3.14 experiments\run_rcaeval_formal_experiment.py `
  --dataset-dir datasets\processed\diagnosis_v8_rcaeval_re2_re3 `
  --output-dir reports\experiments\diagnosis_v8_rcaeval_re2_re3_formal
```

完整性检查：

```powershell
py -3.14 scripts\validate_diagnosis_dataset.py datasets\processed\diagnosis_v7_rcaeval_re2
py -3.14 scripts\validate_diagnosis_dataset.py datasets\processed\diagnosis_v8_rcaeval_re2_re3
```

## 结论边界

实验结果只能表述为“微服务系统多源可观测数据的服务级软件根因诊断”。
不能将结果表述为电子设备硬件故障诊断、软硬件边界定位、FRU 更换预测或维修决策准确率。

