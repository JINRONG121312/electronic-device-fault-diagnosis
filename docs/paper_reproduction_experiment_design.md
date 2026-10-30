# 多源微服务故障诊断论文复现实验设计总表

本表用于后续论文写作，明确每个方法回答的问题、输入协议、输出指标和消融方式。所有结果必须区分“官方数据完整复跑”“跨数据协议适配”“依据论文重实现”。

| 方法 | 核心研究问题 | 模态与输入 | 输出/主指标 | 必做对照与消融 |
|---|---|---|---|---|
| TVDiag | 任务导向和跨模态学习是否提升根因与故障类型联合诊断 | metric、log、trace、服务图 | HR@1/3/5、MRR@3、故障类型 F1 | 去掉 task-oriented、cross-modal、dynamic loss；单模态 |
| Medicine | 模态质量不均衡时，自适应抑制强模态并增强弱模态是否有效 | metric、BERT log、trace | Macro/Weighted P、R、F1 | all/log/metric/trace；关闭 modality evaluation、gradient suppression、feature enhancement |
| Nezha | 将异构观测统一为事件图后，正常/故障模式差异能否细粒度定位 | metric alarms、log templates、trace spans | service AS@1/3/5；inner AIS@1/3/5 | 去掉某一模态；仅事件频次、仅深度；service vs inner |
| RUN | Granger 因果、对比增强和个性化 PageRank 是否优于指标相关性排序 | 指标时间序列和服务图 | HR@K、MRR、平均排名 | 无 Granger、无对比增强、普通 PageRank |
| TORAI | 调用图缺失/盲点下，异常严重度聚类与局部因果分析是否稳健 | metric、log、trace、部分调用图 | HR@K、MRR、缺失模态降幅、运行开销 | 完整图/删边/删节点；严重度聚类和假设检验开关 |
| FAMOS | Gaussian attention 与 cross-attention 是否能学习跨模态关系 | metric、log、trace | HR@K、MRR、故障类型 F1 | early/late fusion；去 Gaussian attention；去 cross-attention |
| Eadro | 联合服务内行为和服务间依赖能否端到端完成检测与根因定位 | metric、log、trace、依赖图 | 检测 F1、HR@K、误报率 | 检测头/定位头拆分；去依赖图；单模态 |
| DiagFusion | 事件嵌入、数据增强和部署/调用图联合建模是否提升诊断 | metric、log、trace、部署图 | HR@K、MRR、故障类型 F1 | 去事件增强、去图模型、单模态 |

## 统一公平性约束

- 同一数据集内固定故障窗口、服务节点词表和候选根因集合。
- 训练、验证、测试按故障注入实例划分，禁止同一注入实例的窗口跨集合泄漏。
- 根因排序使用 HR@K/MRR；故障类型识别使用 Macro/Weighted F1，不能互相替代。
- 报告均值、标准差和至少 3 个随机种子；同时报告模态缺失和噪声扰动下的性能降幅。
- 对 RE2 适配方法，单独列出输入转换规则和信息损失，不与官方数据结果混在同一主表。
