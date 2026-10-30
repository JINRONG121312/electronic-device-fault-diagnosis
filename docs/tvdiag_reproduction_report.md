# TVDiag 官方仓库复现报告

复现时间：2026-07-14（Asia/Shanghai）。

## 上游信息

- 仓库：https://github.com/WHU-AISE/TVDiag
- 克隆目录：`external/TVDiag`
- 固定提交：`cf6f334887036f363807bac1b8995c3b6f47c5db`
- 提交时间：2025-04-28 10:38:41 +08:00
- 官方默认数据集：GAIA、Sockshop
- 官方配置：三模态、任务导向模块开启、跨模态模块开启、动态损失权重、500 epochs、seed=2、early stopping

## 本地环境

- Windows
- Python 3.8.10（项目内隔离运行时）
- PyTorch 2.1.1 CPU
- DGL 2.2.1 CPU
- NumPy 1.24.4
- pandas 2.0.3
- scikit-learn 1.3.2
- tensorboard 2.14.0

本机存在 RTX 4060 Laptop GPU，但 DGL 2.1 CUDA 11.8 没有 Windows wheel，且 WSL 未安装，因此本次使用 CPU 复现。模型结构、损失函数、数据划分、预计算三模态特征和训练参数均保持官方配置。

## 最小兼容修改

1. `process/EventProcess.py`：仅在 `reconstruct=True` 时导入 fastText。默认复现直接使用仓库附带的预计算特征，不需要重新训练 fastText。
2. `core/loss/UnsupervisedContrastiveLoss.py`：将无条件 `.cuda()` 改为 `.to(self.device)`，支持官方代码已有的 CPU 分支。
3. `core/model/Encoder.py`：删除对仓库中不存在、且实际未使用的 `tag.py` 和 `SGC.py` 的悬空导入。实际 GraphSAGE 编码器未修改。

补丁文件见 `experiments/tvdiag_reproduction/tvdiag-windows-cpu.patch`。

## 数据装载验证

| 数据集 | Train | Augmented | Test | 节点数示例 | 三模态维度 |
|---|---:|---:|---:|---:|---|
| GAIA | 160 | 1600 | 939 | 10 | metric/log/trace 均为 128 |
| Sockshop | 248 | 2480 | 241 | 21 | metric/log/trace 均为 128 |

## 完整复跑结果

| 数据集 | 来源 | HR@1 | HR@3 | HR@5 | MRR@3 | 故障类型 F1 |
|---|---|---:|---:|---:|---:|---:|
| GAIA | 仓库作者日志 | 75.932% | 90.948% | 94.569% | 0.827 | 93.633% |
| GAIA | 本次复跑 | 75.932% | 90.948% | 94.569% | 0.827 | 93.633% |
| Sockshop | 仓库作者日志 | 86.307% | 95.436% | 96.266% | 0.903 | 63.564% |
| Sockshop | 本次复跑 | 86.722% | 95.436% | 96.266% | 0.905 | 62.669% |

GAIA 在报告精度下完全复现。Sockshop 的 HR@2、HR@3、HR@4 和 HR@5 一致；HR@1 相差 +0.415 个百分点，故障类型 F1 相差 -0.895 个百分点。训练均在与作者日志相同的 epoch 触发 early stopping（GAIA 125，Sockshop 229），差异主要来自 DGL 版本、CPU/CUDA 执行路径和图算子的非确定性。

## 效率

| 数据集 | 总训练时间 | 平均每 epoch | 总推理时间 |
|---|---:|---:|---:|
| GAIA | 43.06 s | 0.342 s | 8.50 s |
| Sockshop | 139.62 s | 0.607 s | 6.41 s |

完整日志和检查点位于：

- `external/TVDiag/logs/reproduction_full_gaia`
- `external/TVDiag/logs/reproduction_full_sockshop`

## 结论

TVDiag 官方实现已经在本机完成可重复运行，结果与作者仓库日志高度一致。下一步不是直接把该结果与 RE2 比较，而是将 RE2 原始指标、日志和调用链转换为 TVDiag 的 `metrics.json`、`logs.json`、`traces.json`、`nodes.json`、`edges.json` 和 `label.csv` 协议，并沿用当前无泄漏 train/dev/test 划分。
