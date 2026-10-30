# Medicine 复现记录

## 复现边界

Medicine 官方代码（ASE 2024）要求按日期组织的 GAIA/AIOps22 原始 CSV：日志、指标、trace 和故障标签。当前工作区没有 Medicine 所需的 GAIA 原始三模态包；官方 GAIA 下载包按分卷存储，完整包约 5 GB。TVDiag 仓库提供的是同一 GAIA 的已抽取事件缓存，因此本记录使用 **TVDiag-cache adapted reproduction**，不把它写成作者原始数据的完整复现。

## 输入适配

- 来源：`external/TVDiag/data/gaia/tmp/*.pkl` 与 `label.csv`。
- 标签：保留 1099 个样本的样本顺序；`memory_anomalies` 和 `normal memory freed label` 合并为 `memory`，其余映射为 `login`、`file`、`access`。
- 日志：TVDiag 的十个节点、128 维事件向量重复填充为 Medicine 所需的 `[time, 768]`。
- 指标：转换为 `[instance=10, time=1, kpi=128]`。
- trace：十个节点向量按节点均值聚合为 `[invoke=128]`，符合 Medicine 的 `TraceEncoder` 输入。
- 训练/验证/测试：保留 Medicine 官方 trainer 的随机 80/20、再从训练集划 80/20 逻辑；这不是当前 RE2 的固定无泄漏划分。

适配脚本：`experiments/medicine_reproduction/run_tvdig_cache_adapted.py`。

## Smoke 结果

运行环境为 TVDiag Python 3.8 环境、PyTorch 2.1.1 CPU、NumPy 1.24.4、pandas 2.0.3、transformers 4.37.2，`--epochs 1 --limit 128`。

| 指标 | 结果 |
|---|---:|
| 样本数 | 128 |
| 故障类别 | 4 |
| Macro precision | 0.5833 |
| Macro recall | 0.6111 |
| Macro F1 | 0.5887 |
| Weighted precision | 0.8077 |
| Weighted recall | 0.8462 |
| Weighted F1 | 0.8152 |

结果文件：`experiments/medicine_reproduction/data/gaia_tvdig_adapted_128/run_result.json`。

这些数值只证明 Medicine 的三模态编码、ConcatFusion 和自适应梯度优化链路在当前缓存协议下可运行，不能与论文中原始 GAIA/AIOps22 结果直接比较。

## 正式实验设计

1. **主结果**：在作者原始 GAIA/AIOps22 数据上报告故障类型 Macro/Weighted P/R/F1。
2. **模态消融**：`all`、`log`、`metric`、`trace`，保持随机种子、划分和训练轮数一致。
3. **优化消融**：关闭 modality evaluation、gradient suppression、feature enhancement，分别替换为普通联合交叉熵。
4. **稳健性**：按故障类别和模态缺失（去掉日志、指标或 trace）分组报告 Macro F1。
5. **公平性**：Medicine 只输出故障类型分类；根因服务定位必须另接一个显式 RCA 头，不能把分类 F1 当作 HR@K。
