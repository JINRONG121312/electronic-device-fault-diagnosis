# 项目结构与模块说明（带代码注释）

本文档整理当前项目在清理后的真实结构，说明各模块职责、核心文件、调用关系，以及关键代码如何串联成“证据采集 -> 故障诊断 -> 图模型推理 -> 前端可视化 -> 实验评估”的完整流程。

## 1. 总体定位

本项目是一个面向计算机设备故障诊断的研究原型。它不是单纯的“换哪个 FRU”的工具，而是把日志、设备画像、运行指标、主动测试、崩溃转储、知识规则和公开日志数据集统一到一个可解释诊断流程里。

当前主线可以概括为：

```text
本机/远程/离线证据
-> 标准化 DatasetCase / runtime_info
-> 异常检测与故障分类
-> 异构诊断图构建
-> 图推理与证据融合
-> 决策层输出修复/补采/替换建议
-> 前端图可视化与实验评估
```

## 2. 当前目录结构

```text
project (2)/
  main.py                         # Web 服务主入口
  fru_web_server.py               # 本地仪表盘 HTTP API 与静态文件服务
  target_agent.py                 # 被诊断机器上运行的远程采集 agent

  fru_diagnosis/                  # 主实现包：诊断、图模型、采集配置、数据结构
    diagnostic_workflow.py        # 端到端诊断编排
    diagnosis_engine.py           # 候选打分、图融合、诊断报告
    diagnostic_graph.py           # 异构故障诊断图构建
    graph_inference.py            # 图传播/PPR 推理
    evidence_fusion.py            # 多源证据融合
    fault_classification.py       # 故障类别分类
    anomaly_detection.py          # 异常检测
    boundary_assessment.py        # 软硬件/边界归因评估
    active_diagnosis.py           # 下一步主动测试推荐
    crash_diagnosis.py            # BugCheck/崩溃转储映射
    crash_dump_evidence.py        # 崩溃转储证据规范化
    health_assessment.py          # 健康状态评估
    log_noise_reduction.py        # 日志噪声削减
    dashboard_data.py             # 前端 dashboard payload 构造
    collection_config.py          # 采集配置与历史快照
    device_setup.py               # 设备画像建立
    model_registry.py             # 设备/型号知识索引
    remote_diagnosis.py           # 远程描述/离线证据规范化
    remote_agent_client.py        # 与 target_agent 通信
    web_api.py                    # API 路由辅助
    datasets/
      schema.py                   # DatasetCase / EvidenceBundle / Label
      adapters/                   # Loghub / Backblaze / OpenRepair 转换适配器

  fault_diagnosis/                # 面向论文/研究命名空间的 facade
  web/                            # 前端页面、交互逻辑、故障图可视化
  scripts/                        # PowerShell 采集脚本与 Loghub 数据处理脚本
  experiments/                    # 实验 baseline 与评估脚本
  datasets/                       # 原始与处理后的公开数据集
  knowledge/                      # 本体、规则、信号目录、设备知识库
  configs/                        # 设备画像与采集配置
  reports/                        # 运行日志、实验指标、报告与锁文件
  tests/                          # 单元测试
  docs/                           # 项目文档与实验报告
```

## 3. 分层架构

```text
前端层
  web/index.html, web/app.js, web/styles.css
  展示 dashboard、诊断结果、故障图、Loghub 实验结果

Web/API 层
  fru_web_server.py, fru_diagnosis/web_api.py
  提供 /api/dashboard、/api/diagnose、/api/experiments/loghub-os 等接口

诊断编排层
  fru_diagnosis/diagnostic_workflow.py
  将异常检测、分类、图诊断、边界判断、决策、下一步测试串起来

模型与推理层
  fru_diagnosis/diagnosis_engine.py
  fru_diagnosis/diagnostic_graph.py
  fru_diagnosis/graph_inference.py
  负责候选打分、异构图构建、图传播推理和可解释排序

证据与数据层
  fru_diagnosis/datasets/schema.py
  fru_diagnosis/log_noise_reduction.py
  scripts/collect_runtime_info.ps1
  scripts/prepare_loghub_os_dataset.py
  负责采集、清洗、标准化和数据集构造

知识层
  knowledge/
  提供规则、本体、设备型号、FRU/非 FRU 信号和解释文本

实验层
  experiments/run_baselines.py
  experiments/evaluate_cases.py
  运行 keyword baseline 与 graph_fusion baseline，并输出指标
```

## 4. 启动入口与 Web 服务

### 4.1 main.py

`main.py` 只做一件事：把项目入口转发到 Web 服务。

```python
from fru_web_server import main as run_web_server


def main() -> int:
    # 统一入口：python main.py --host 127.0.0.1 --port 8780
    return run_web_server()
```

这样做的好处是：命令行入口稳定，真正的服务逻辑集中在 `fru_web_server.py`。

### 4.2 fru_web_server.py

`fru_web_server.py` 是本地研究 dashboard 的后端核心，职责包括：

- 提供静态前端页面；
- 暴露诊断 API；
- 触发 PowerShell 采集脚本；
- 管理后台采集任务；
- 导入/展示 Loghub 弱标签实验；
- 提供故障图数据给前端。

核心路由结构：

```python
def build_api_routes(handler: "FRURequestHandler") -> ApiRoutes:
    return ApiRoutes(
        get={
            "/api/dashboard": lambda _query: ok(build_configured_dashboard_payload()),
            "/api/health": lambda _query: ok({...}),
            "/api/job": handler.api_get_job,
            "/api/settings": lambda _query: ok(build_settings_payload()),
            "/api/experiments/loghub-os": lambda query: ok(
                build_loghub_os_experiment_payload(query)
            ),
        },
        post={
            "/api/diagnose": handler.api_diagnose,
            "/api/remote-diagnosis": handler.api_remote_diagnosis,
            "/api/target/probe": handler.api_target_probe,
            "/api/target/collect": handler.api_target_collect,
            "/api/experiments/loghub-os/import": lambda body: ok(
                import_loghub_os_experiment(body)
            ),
        },
    )
```

诊断 API 的核心逻辑：

```python
def api_diagnose(self, body: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
    profile = read_json(DEFAULT_ACTIVE_PROFILE_PATH, default={})
    settings = load_collection_settings()
    runtime = read_json(resolve_active_runtime_path(settings), default={})
    mode = str(body.get("mode", "") or "").strip()

    # run_diagnostic_workflow 会返回 classification、decision、
    # diagnostic_graph、graph_inference 等前端需要的诊断结果。
    return ok(run_diagnostic_workflow(mode, body, profile, runtime=runtime))
```

## 5. 诊断编排模块

文件：`fru_diagnosis/diagnostic_workflow.py`

这个模块是项目的“流水线总控”。它区分本机诊断和跨机器诊断，然后调用各个子模块。

```python
def run_diagnostic_workflow(
    mode: str,
    body: dict[str, Any],
    profile: dict[str, Any],
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode or body.get("mode"))
    if normalized_mode == SELF_DETECTION:
        return run_self_detection(body, profile, runtime or {})
    return run_cross_machine_detection(normalized_mode, body, profile)
```

本机诊断流程：

```python
def run_self_detection(body, profile, runtime):
    symptoms = normalize_symptoms(body.get("symptoms") or body.get("symptom"))
    runtime = normalize_runtime_crash_dump(runtime, "self_after_reboot")

    anomaly = detect_anomalies(runtime, symptoms)
    health = assess_device_health(runtime, anomaly)
    case = build_self_fault_case(symptoms, runtime, anomaly)
    classification = classify_fault_case(case)

    # 关键：诊断报告里已经包含 diagnostic_graph 和 graph_inference。
    diagnosis_report = build_diagnosis_report(profile, runtime)

    boundary = assess_boundary(
        runtime,
        classification,
        diagnosis_report.get("top_candidates", []),
        symptoms,
    )
    decision = decide_after_classification(classification)
    next_tests = recommend_next_tests(diagnosis_report, symptoms, limit=5)

    return {
        "anomaly_detection": anomaly,
        "classification": classification,
        "boundary_assessment": boundary,
        "decision": decision,
        "next_tests": next_tests,
        "top_candidates": diagnosis_report.get("top_candidates", []),
        "diagnostic_graph": diagnosis_report.get("diagnostic_graph", {}),
        "graph_inference": diagnosis_report.get("graph_inference", {}),
    }
```

## 6. 诊断引擎与候选打分

文件：`fru_diagnosis/diagnosis_engine.py`

该模块负责把设备画像、运行时证据、规则和图推理结果合并为最终诊断报告。

```python
def build_diagnosis_report(profile, runtime, coverage=None, collection_plan=None):
    # 1. 根据设备 profile 中的 FRU/子系统定义打分
    candidates = [
        score_fru(fru, runtime, coverage.get(str(fru.get("id", "")), {}), plan_by_fru)
        for fru in profile.get("fru_list", [])
        if fru.get("diagnosis_role") in {"target_fru", "subsystem"}
    ]

    # 2. 加入非 FRU 候选，如 driver_or_os_fault、firmware_or_config_fault
    candidates.extend(score_non_fru_fault(fault, runtime, candidates) for fault in NON_FRU_FAULTS)

    # 3. 构建异构诊断图，并进行图传播推理
    diagnostic_graph = build_diagnostic_graph(profile, runtime, candidates=candidates)
    graph_inference = infer_diagnostic_graph(diagnostic_graph)

    # 4. 将图推理后验分数融合回候选排序
    candidates = apply_graph_inference_to_candidates(candidates, graph_inference)
    candidates.sort(key=lambda item: item["rank_score"], reverse=True)

    return {
        "top_candidates": candidates[:5],
        "candidates": candidates,
        "diagnostic_graph": compact_graph_for_report(diagnostic_graph),
        "graph_inference": compact_graph_inference_for_report(graph_inference),
        "method": {
            "name": "heterogeneous_graph_fused_fault_diagnosis",
        },
    }
```

这里体现了项目的核心创新点：不再只靠关键词把样本压到单一类别，而是把多源证据组织成图，再通过图推理给候选和故障类分配后验支持。

## 7. 异构故障诊断图

文件：`fru_diagnosis/diagnostic_graph.py`

### 7.1 图节点与边

图中主要节点类型：

| 节点类型 | 含义 |
|---|---|
| `case` | 当前诊断案例 |
| `log_template` | 日志模板或日志片段 |
| `weak_signal` | 弱标签或规则信号 |
| `component` | 日志来源组件/设备组件 |
| `candidate` | 候选故障目标，如 driver_or_os_fault、battery_pack |
| `fault_class` | 故障类别，如 os_fault、driver_fault、hardware_fault |
| `metric_signal` | 指标异常 |
| `active_test` | 主动测试结果 |
| `crash_signature` | 崩溃转储签名 |

主要边类型：

| 边类型 | 含义 |
|---|---|
| `contains` | case 包含某类证据 |
| `emitted_by` | 日志由某组件产生 |
| `supports_candidate` | 证据支持某候选 |
| `supports_fault` | 证据支持某故障类 |
| `contradicts_candidate` | 证据反驳某候选 |
| `maps_to_fault` | 候选映射到故障类 |

### 7.2 GraphBuilder

```python
class GraphBuilder:
    def add_node(self, node_id, node_type, label, prior=0.0, metadata=None):
        # node_id 是稳定 ID，例如 fault:os_fault、candidate:driver_or_os_fault
        # prior 表示这个证据节点自身的重要性或先验强度。
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "prior": round(max(0.0, prior), 4),
            "metadata": metadata or {},
        }

    def add_edge(self, source, target, edge_type, weight=1.0, metadata=None):
        # weight 是支持/冲突强度，metadata 里保留 reason，方便前端解释。
        self.edges.append({
            "source": source,
            "target": target,
            "type": edge_type,
            "weight": round(weight, 4),
            "metadata": metadata or {},
        })
```

### 7.3 从 DatasetCase 构图

```python
def build_diagnostic_graph_from_case(case: DatasetCase, profile=None, candidates=None):
    # 实验脚本不需要真实设备 profile，也可以从标准化 DatasetCase 构建图。
    return build_diagnostic_graph(
        profile or {},
        runtime_from_case(case),
        candidates=candidates,
    )
```

### 7.4 Loghub 风格日志构图

```python
def add_loghub_style_logs(builder: GraphBuilder, logs: dict[str, Any]) -> None:
    # 1. 把 component_counts 加为 component 节点
    # 2. 把 event_template_counts 加为 log_template 节点
    # 3. 结合 actionable_warning_error_count 调整 prior
    # 4. 将日志文本映射到 candidate / fault_class
    for template, count in sorted(template_counts.items(), key=lambda item: item[1], reverse=True)[:20]:
        node_id = f"log:{stable_hash(normalize_template(text))}"
        builder.add_node(node_id, "log_template", text[:120], prior=prior)
        builder.add_edge("case:current", node_id, "contains", weight=0.25)
        link_text_to_targets(builder, node_id, text, base_weight=0.7 if actionable_count else 0.1)

    if actionable_count == 0:
        # 如果噪声削减后没有可行动异常事件，显式支持 no_fault_observed。
        builder.add_node("signal:no_actionable_log_event", "weak_signal", "no actionable log event", prior=0.4)
        builder.add_edge("signal:no_actionable_log_event", "fault:no_fault_observed", "supports_fault", weight=0.8)
```

## 8. 图推理模块

文件：`fru_diagnosis/graph_inference.py`

图推理采用轻量级、无外部依赖的 PPR/证据传播 baseline。后续可以替换成 R-GCN、HGT 或其他图神经网络，但当前实现便于解释和测试。

```python
def infer_diagnostic_graph(graph, restart_prob=0.35, iterations=18):
    nodes = {str(node["id"]): node for node in graph.get("nodes", [])}
    edges = [edge for edge in graph.get("edges", []) if edge.get("source") in nodes]

    # 1. 根据边类型建立传播邻接表
    adjacency = build_adjacency(edges)

    # 2. 从日志、指标、主动测试、崩溃签名等证据节点生成 seed
    seed = seed_distribution(nodes)

    # 3. 个性化 PageRank 式传播
    posterior = personalized_pagerank(nodes, adjacency, seed, restart_prob=restart_prob, iterations=iterations)

    # 4. 直接统计 support/conflict 边
    direct = direct_evidence_scores(nodes, edges)

    # 5. 对 candidate 和 fault_class 分别排序
    candidate_scores = rank_nodes("candidate", nodes, posterior, direct)
    fault_scores = rank_nodes("fault_class", nodes, posterior, direct)

    return {
        "candidate_ranking": candidate_scores,
        "fault_ranking": fault_scores,
        "node_posterior": {...},
        "direct_evidence": direct,
    }
```

这里的关键思想是：图结构负责多跳传播，直接证据边负责可解释校准。最终输出既有排序，也有 supporting_paths / conflicting_paths，前端可以展示证据路径。

## 9. 数据结构与数据集模块

文件：`fru_diagnosis/datasets/schema.py`

项目统一使用 `DatasetCase` 表达来自本机运行时、Loghub、Backblaze、OpenRepair 或手工导入的案例。

```python
@dataclass(frozen=True)
class EvidenceBundle:
    # 证据被拆成六类，方便不同来源数据统一接入。
    inventory: dict[str, Any] = field(default_factory=dict)
    logs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    active_tests: dict[str, Any] = field(default_factory=dict)
    crash_dump: dict[str, Any] = field(default_factory=dict)
    repair_result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Label:
    # label 可以是真实标签，也可以是弱标签。
    fault_origin: str              # no_fault_observed / non_fru_fault / replaceable_fru
    target: str                    # none / driver_or_os_fault / os_fault / ...
    serviceability_type: str       # none / non_fru_fault / replaceable_fru
    confidence: str = "unknown"
    source: str = ""


@dataclass(frozen=True)
class DatasetCase:
    # 一个可复现实验样本。
    case_id: str
    source_dataset: str
    device_type: str
    symptom: tuple[str, ...] = field(default_factory=tuple)
    evidence: EvidenceBundle = field(default_factory=EvidenceBundle)
    label: Label | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

本机 runtime_info 转 DatasetCase：

```python
def case_from_runtime_info(runtime, case_id, symptom=(), label=None, metadata=None):
    evidence = EvidenceBundle(
        inventory={
            "system": runtime.get("system", {}),
            "device_inventory": runtime.get("device_inventory", {}),
        },
        logs={"events": runtime.get("events", {})},
        metrics={
            "battery": runtime.get("battery", {}),
            "storage": runtime.get("storage", {}),
            "memory": runtime.get("memory", {}),
            "network": runtime.get("network", {}),
        },
        active_tests=runtime.get("tests", {}),
        crash_dump=runtime.get("crash_dump", {}),
    )
    return DatasetCase(case_id=case_id, source_dataset="local_runtime", evidence=evidence, label=label)
```

## 10. Loghub 弱标签数据处理

文件：`scripts/prepare_loghub_os_dataset.py`

该脚本处理 Loghub Linux/Windows/Mac 的结构化日志。由于这些数据集没有官方故障标签，脚本会：

1. 读取结构化 CSV；
2. 按窗口切片；
3. 做模板级日志噪声削减；
4. 根据保守规则产生弱标签；
5. 输出 `all/train/dev/test` JSONL；
6. 生成 prompt 模板，供人工或 LLM 审查弱标签。

生成文件位于：

```text
datasets/processed/diagnosis_v3_loghub2k/
  all.jsonl
  all_pred.jsonl                  # graph_fusion 默认预测
  all_pred_rule_weighted.jsonl    # keyword baseline 对照预测
  train.jsonl
  dev.jsonl
  test.jsonl
  linux.jsonl
  windows.jsonl
  mac.jsonl
  stats.json
  prompts/
```

## 11. 实验模块

### 11.1 预测脚本

文件：`experiments/run_baselines.py`

当前有两个方法：

| 方法 | 作用 |
|---|---|
| `rule_weighted` | 旧关键词基线，用于对照类别塌缩问题 |
| `graph_fusion` | 使用诊断图和图推理的 baseline |

图融合预测核心：

```python
def predict_graph_fusion(case: DatasetCase) -> dict[str, object]:
    graph = build_diagnostic_graph_from_case(case)
    inference = infer_diagnostic_graph(graph)

    fault_ranking = inference.get("fault_ranking", [])
    candidate_ranking = inference.get("candidate_ranking", [])

    top_fault = first_supported_item(fault_ranking)

    # 如果图上 no_fault_observed 是最强故障类，不能再被弱候选覆盖。
    if str((top_fault or {}).get("id", "")) == "no_fault_observed":
        target = "none"
    else:
        top_candidate = first_supported_item(candidate_ranking)
        target = map_candidate_target(top_candidate, top_fault)

    return {
        "method": "graph_fusion_baseline",
        "fault_origin": map_fault_origin(top_fault, target),
        "target": target,
        "target_ranking": build_target_ranking(candidate_ranking, fault_ranking),
        "graph_fault_ranking": compact_ranking(fault_ranking),
        "graph_candidate_ranking": compact_ranking(candidate_ranking),
    }
```

### 11.2 评估脚本

文件：`experiments/evaluate_cases.py`

评估内容包括：

- `fault_origin_accuracy`
- `target_accuracy`
- `top3_target_accuracy`
- `serviceability_type_accuracy`
- `mean_reciprocal_rank`
- `target_macro_f1`
- `fault_origin_macro_f1`
- 混淆矩阵
- 预测分布

```python
def evaluate(cases: list[DatasetCase]) -> dict[str, Any]:
    labeled = [case for case in cases if case.label is not None]
    with_predictions = [
        case for case in labeled
        if isinstance(case.metadata.get("prediction"), dict)
    ]

    target_matrix = build_confusion_matrix(with_predictions, "target")
    fault_origin_matrix = build_confusion_matrix(with_predictions, "fault_origin")

    return {
        "target_accuracy": accuracy(with_predictions, "target"),
        "top3_target_accuracy": topk_accuracy(with_predictions, "target", k=3),
        "target_macro_f1": macro_average(target_matrix["per_class"], "f1"),
        "fault_origin_macro_f1": macro_average(fault_origin_matrix["per_class"], "f1"),
        "prediction_distribution": prediction_distribution(with_predictions, "target"),
        "target_confusion_matrix": target_matrix,
    }
```

## 12. 前端模块

目录：`web/`

| 文件 | 作用 |
|---|---|
| `index.html` | 页面结构，包含自检、远程诊断、实验、故障图容器 |
| `app.js` | 前端状态管理、API 调用、诊断结果渲染、SVG 故障图绘制 |
| `api_client.js` | API 路由封装 |
| `styles.css` | 页面样式和故障图样式 |

### 12.1 API 客户端

```javascript
const API_ROUTES = Object.freeze({
  dashboard: "/api/dashboard",
  diagnose: "/api/diagnose",
  remoteDiagnosis: "/api/remote-diagnosis",
  loghubOsExperiment: "/api/experiments/loghub-os",
});

const dashboardApi = Object.freeze({
  diagnose: (body) => apiRequest(API_ROUTES.diagnose, {
    method: "POST",
    body: JSON.stringify(body),
  }),
  getLoghubOsExperiment: (params = {}) => {
    const query = new URLSearchParams(params);
    return apiRequest(`${API_ROUTES.loghubOsExperiment}?${query.toString()}`);
  },
});
```

### 12.2 故障图可视化

文件：`web/app.js`

关键函数：

```javascript
function renderDiagnosticGraphPanel({ diagnosis, containerId, detailId }) {
  const graph = diagnosis.diagnostic_graph || {};
  const inference = diagnosis.graph_inference || {};

  // graph.nodes / graph.edges 来自后端 diagnostic_graph。
  // inference.candidate_ranking / fault_ranking 用于展示排序和解释路径。
  return `
    <div class="diagnosis-graph-summary">...</div>
    <div class="diagnosis-graph-layout">
      <div class="diagnosis-graph-canvas">
        ${renderDiagnosticGraphSvg(graph)}
      </div>
      <aside class="diagnosis-graph-detail" id="${detailId}">
        ${renderGraphDetail(...)}
      </aside>
    </div>
  `;
}
```

节点和边由 SVG 原生绘制，不依赖额外图库：

```javascript
function renderGraphNode(node, position) {
  // 根据 node.type 决定颜色、形状和文本。
  // candidate / fault_class / log_template / weak_signal 会被区分显示。
}

function renderGraphEdge(edge, positions) {
  // 根据 edge.type 决定线条样式。
  // supports_candidate / supports_fault 代表支持；
  // contradicts_candidate 代表冲突。
}
```

## 13. 远程诊断与 target_agent

文件：

- `target_agent.py`
- `fru_diagnosis/remote_agent_client.py`
- `fru_diagnosis/remote_diagnosis.py`

目标场景：一台机器诊断另一台机器。

```text
诊断端浏览器
-> /api/target/probe
-> target_agent.py /health
-> /api/target/collect
-> target_agent.py /collect
-> runtime_info / evidence_package
-> run_diagnostic_workflow("cross_machine_interface", ...)
```

这部分让系统不仅支持“本机自检”，也支持“远程描述 + 远程采集包 + 离线证据导入”。

## 14. 配置、知识库与报告

### 14.1 configs/

保存当前设备画像和采集设置：

```text
configs/active_device.json        # 当前启用设备画像
configs/collection_settings.json  # 采集窗口、历史保留、后台采集配置
configs/*.json                    # 不同设备型号示例
```

### 14.2 knowledge/

保存规则和知识资产：

```text
knowledge/rules/                  # OS、Linux、BSOD 规则
knowledge/ontology/               # 故障、边界、FRU/非 FRU 本体
knowledge/fru_signal_catalog.json # 证据信号目录
knowledge/*/model_registry.json   # 型号/设备知识索引
```

### 14.3 reports/

保存运行结果和实验指标：

```text
reports/experiment_metrics/
diagnosis_v3_loghub2k_graph_metrics.json
diagnosis_v3_loghub2k_rule_metrics.json

reports/locks/
  web_127_0_0_1_8780.lock         # 当前 Web 服务锁
```

## 15. 测试模块

目录：`tests/`

测试覆盖主要包括：

- 数据集 schema 与 adapters；
- Loghub OS 数据处理；
- 诊断图构建和图推理；
- Web API 边界；
- 远程 agent client；
- 诊断 workflow；
- 健康评估、边界评估、日志噪声削减；
- 实验脚本。

当前全量测试结果：

```text
Ran 93 tests
OK
```

## 16. 关键调用链总结

### 16.1 本机诊断

```text
web/app.js
-> POST /api/diagnose
-> fru_web_server.py::api_diagnose
-> diagnostic_workflow.run_diagnostic_workflow
-> run_self_detection
-> detect_anomalies
-> classify_fault_case
-> build_diagnosis_report
-> build_diagnostic_graph
-> infer_diagnostic_graph
-> assess_boundary
-> decide_after_classification
-> recommend_next_tests
-> 前端 renderDiagnosticGraphPanel
```

### 16.2 Loghub 实验

```text
scripts/prepare_loghub_os_dataset.py
-> datasets/processed/diagnosis_v3_loghub2k/all.jsonl
-> experiments/run_baselines.py --method graph_fusion
-> build_diagnostic_graph_from_case
-> infer_diagnostic_graph
-> all_pred.jsonl
-> experiments/evaluate_cases.py --json
-> reports/experiment_metrics/*.json
-> /api/experiments/loghub-os
-> web/app.js 实验页面
```

### 16.3 远程诊断

```text
web/app.js
-> /api/target/probe 或 /api/target/collect
-> remote_agent_client.py
-> target_agent.py
-> runtime_info/evidence_package
-> run_diagnostic_workflow("cross_machine_interface")
-> diagnostic_graph + graph_inference
-> 前端展示诊断图
```

## 17. 当前项目状态判断

当前项目已经从“关键词排序打分原型”演进为：

1. 有标准化证据 schema；
2. 有日志噪声削减和弱标签数据集构造；
3. 有异构诊断图构建；
4. 有图传播推理 baseline；
5. 有前端故障图可视化；
6. 有 Loghub 弱标签实验与 macro-F1/混淆矩阵评估；
7. 有本机、远程和离线诊断的统一 workflow。

后续最值得继续做的是：

- 训练或校准“图 fault_class -> 数据集 target 标签”的映射层；
- 将 `graph_fusion` 从实验 baseline 进一步纳入正式诊断报告评分；
- 增加弱标签人工审核或 LLM 辅助审核闭环；
- 把前端故障图的节点点击解释与实验样本详情进一步联动。
