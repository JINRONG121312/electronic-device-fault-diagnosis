# Nezha 复现记录

## 仓库与运行环境

- 官方仓库：<https://github.com/IntelligentDDS/Nezha>
- HEAD：`d8140101fdb4e7dfb60d3ef9f64706f382b68470`
- 数据：仓库自带 Online Boutique（OnlineBoutique/hipster）和 TrainTicket（ts）故障数据、无故障构造数据及作者标签。
- 运行环境：项目 TVDiag Python 3.8 环境；补充 `drain3==0.9.10`、`more_itertools==8.12.0`、`psutil==5.9.0`、`PyYAML==6.0.1`。
- 版本对照环境：`external/.runtime/python36/python.exe`（Python 3.6.8、NumPy 1.15.4、pandas 0.23.4），按仓库 `requirements.txt` 安装。

## Windows 兼容补丁

1. `alarm.py` 中 matplotlib 仅用于绘图且不参与 RCA，改为可选导入。
2. `data_integrate.py` 中作者固定 `max_workers=64` 超过 Windows 进程池上限，改为运行时最多 8 个 worker。
3. 启动时使用 `python .\main.py`，确保 `dirname(__file__)` 正确解析日志目录。

## 实验设计

Nezha 将指标告警、日志模板和 trace span 转成统一事件，分别构建正常窗口与故障窗口的事件图，使用事件模式支持度变化和深度进行排序。

| 实验 | 输入 | 标签粒度 | 指标 |
|---|---|---|---|
| Online Boutique service | metric + log + trace | 注入 pod/service | AS@1、AS@3、AS@5 |
| Online Boutique inner | 同上 | 代码区域/资源类型 | AIS@1、AIS@3、AIS@5 |
| TrainTicket service | metric + log + trace | 注入 service | AS@1、AS@3、AS@5 |
| TrainTicket inner | 同上 | 代码区域/资源类型 | AIS@1、AIS@3、AIS@5 |

作者 README 报告：Online Boutique service/inner 为 92.857/96.429/96.429%，TrainTicket service/inner 为 86.667/97.778/97.778%。

## 本地子集结果与差异

使用作者 Online Boutique fault list 的前 3 个故障、同一正常窗口和同一排序函数，分别在 Python 3.8/NumPy 1.24/pandas 2.0 与隔离的 Python 3.6/NumPy 1.15.4/pandas 0.23.4 环境运行，两个环境均得到 AS@1/3/5 = 0/0/0。Python 3.8 运行还出现 trace 时间戳 `invalid value encountered in cast` 警告；Python 3.6 消除了该警告但结果仍未达到作者日志。

这说明当前 HEAD 的多进程 `as_completed` 事件图收集顺序、Drain 模板持久化状态或作者生成日志时的未公开环境会影响候选模式排序。当前状态应标记为 **official-data partial reproduction / mismatch**，不能把 README 的作者数值写成本地复现值。仓库作者日志仍保留为独立的论文对照。

子集日志：`external/Nezha/log/2026-07-21_nezha.log`；子集标签文件由 `experiments/nezha_reproduction/run_official_subset.py` 生成。

Nezha 与 Medicine 的指标不可混用：Nezha 的 AS/AIS 是根因排序命中率，Medicine 的 P/R/F1 是故障类型分类指标。
