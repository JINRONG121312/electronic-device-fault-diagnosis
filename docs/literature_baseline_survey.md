# 微服务根因诊断文献基线调研与复现范围

> 本文件记录第一轮 RCAEval 适配复现。2022-2026 高水平方法的重新筛选结果见 `docs/recent_high_rank_microservice_rca_survey.md`；论文选基线应以后者为准。

## 基线选择原则

论文中的主要基线必须同时满足：公开论文或正式基准可追溯、输入模态与 RE2 数据匹配、输出可以映射为根因服务或 `service:fault_type`、实现差异能够明确说明。

当前工程中的多数类、关键词规则和 TF-IDF 方法只保留为 sanity check，不再作为证明方法先进性的主要文献基线。

## 第一批复现方法

| 方法 | 文献/来源 | 原始输入 | 本项目状态 | 论文中的名称 |
|---|---|---|---|---|
| BARO | Pham et al., FSE 2024 | 指标时间序列 | 已完成适配复现 | BARO (adapted reproduction) |
| Multi-source BARO | RCAEval 官方多源基线 | 指标、日志时间序列、调用链时间序列 | 已完成适配复现 | Multi-source BARO (adapted reproduction) |
| CloudRanger | Wang et al., CCGRID 2018 | KPI 与因果/依赖图 | 已完成服务图适配复现 | CloudRanger (adapted reproduction) |
| TraceRCA | RCAEval 官方 trace baseline | 完整 span/trace | 已完成聚合 span 适配复现 | TraceRCA (aggregate-span reproduction) |

RCAEval 官方仓库明确列出了 BARO、TraceRCA、Multi-source BARO 等 15 类可复现基线，并提供 RE2 数据协议。因此第一批实现以 RCAEval 官方代码语义为依据，而不是根据论文名称自行构造同名模型。

## 适配边界

本项目的规范化案例保存了完整指标 CSV 路径，但日志和调用链在案例对象中是聚合统计。因此：

- BARO 可以按原实现的 RobustScaler 思路复现故障前后指标变化，再把指标节点映射到训练集服务标签空间。
- Multi-source BARO 的指标部分按原始时序计算；日志和调用链部分使用聚合异常计数，不能声称是字节级官方结果复现。
- CloudRanger 的服务依赖图由训练集失败 span 的调用操作重建，测试标签不参与图构建。
- TraceRCA 缺少完整 trace ID 与正常 span 序列，只能复现 support-confidence 排序框架。

因此报告统一使用“适配复现”，不能写成“完全复现原论文数值”。要进行完全复现，应在独立 Python 3.12/Linux 环境直接运行 RCAEval 官方包及其原始 RE2 格式。

## 下一批优先级

1. Eadro：与本文多源融合最接近，应作为最重要的深度模型基线，但需要其训练网络、窗口划分和依赖版本。
2. MicroRCA：适合服务级性能根因定位，需要完整服务依赖和指标相关性。
3. RCD/CIRCA：适合作为因果发现基线，但官方依赖独立 Python 3.8 环境，运行成本明显更高。
4. TORAI：面向服务调用图盲点的多源 RCA，可作为较新的强基线；需使用官方预聚合 TORAI 数据协议。

## 已核验文献

- Pham, L., Ha, H., Zhang, H. BARO: Robust Root Cause Analysis for Microservices via Multivariate Bayesian Online Change Point Detection. FSE 2024. DOI: [10.1145/3660805](https://doi.org/10.1145/3660805).
- Pham, L., Zhang, H., Ha, H., Salim, F., Zhang, X. RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data. WWW Companion 2025. DOI: [10.1145/3701716.3715290](https://doi.org/10.1145/3701716.3715290).
- Wang, P. et al. CloudRanger: Root Cause Identification for Cloud Native Systems. CCGRID 2018. DOI: [10.1109/CCGRID.2018.00076](https://doi.org/10.1109/CCGRID.2018.00076).
- Wu, L., Tordsson, J., Elmroth, E., Kao, O. MicroRCA: Root Cause Localization of Performance Issues in Microservices. NOMS 2020. DOI: [10.1109/NOMS47738.2020.9110353](https://doi.org/10.1109/NOMS47738.2020.9110353).
- Lee, C., Yang, T., Chen, Z., Su, Y., Lyu, M. R. Eadro: An End-to-End Troubleshooting Framework for Microservices on Multi-source Data. ICSE 2023. DOI: [10.1109/ICSE48619.2023.00150](https://doi.org/10.1109/ICSE48619.2023.00150).

官方实现来源：[RCAEval GitHub](https://github.com/phamquiluan/RCAEval)，核验日期为 2026-07-12。
