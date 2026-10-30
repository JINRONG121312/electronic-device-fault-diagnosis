"""Generate visual reports for diagnosis experiment metrics.

The script uses only the Python standard library and writes a standalone HTML
report plus SVG charts from metrics_summary.json and per_source_metrics.json.
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENT_DIR = Path("reports/experiments/diagnosis_v3_loghub2k")

METHOD_LABELS = {
    "rule_weighted": "规则加权",
    "graph_fusion": "图融合",
}

SPLIT_LABELS = {
    "silver_test": "银标签主实验",
    "weak_test": "弱标签辅助实验",
    "mixed_test": "混合管线实验",
}

METRIC_LABELS = {
    "fault_origin_accuracy": "故障边界准确率",
    "target_accuracy": "根因目标准确率",
    "top3_target_accuracy": "Top-3 根因覆盖率",
    "target_macro_f1": "根因 Macro-F1",
    "serviceability_type_accuracy": "服务性准确率",
}

HARDWARE_TARGETS = {
    "io_board",
    "ram_module",
    "wlan_module",
    "power_adapter",
    "storage_fru",
    "battery_pack",
    "motherboard",
}

DISPLAY_TARGET_LABELS = {
    "none": "无故障观察",
    "os_fault": "操作系统/服务故障",
    "driver_or_os_fault": "驱动/系统故障",
    "firmware_or_config_fault": "固件/配置故障",
    "external_environment_fault": "外部环境故障",
    "data_or_filesystem_fault": "数据/文件系统故障",
    "io_board": "I/O 板候选",
    "ram_module": "内存模块候选",
    "wlan_module": "无线网卡候选",
    "power_adapter": "电源适配器候选",
    "storage_fru": "存储 FRU 候选",
    "battery_pack": "电池包候选",
    "motherboard": "主板候选",
    "unknown": "未知",
    "mixed_or_uncertain": "混合/不确定",
}

PALETTE = {
    "graph": "#287c71",
    "rule": "#b05d2b",
    "blue": "#3f6ea8",
    "amber": "#c98424",
    "red": "#b84e4e",
    "green": "#287c71",
    "ink": "#263238",
    "muted": "#6f7b83",
    "grid": "#d9dee3",
    "panel": "#f7f8fa",
    "paper": "#ffffff",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize diagnosis experiment results.")
    parser.add_argument("--experiment-dir", default=str(DEFAULT_EXPERIMENT_DIR))
    args = parser.parse_args()

    experiment_dir = Path(args.experiment_dir)
    summary = read_json(experiment_dir / "metrics_summary.json")
    per_source = read_json(experiment_dir / "per_source_metrics.json")
    charts_dir = experiment_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    chart_paths = {
        "silver": charts_dir / "silver_main_metrics.svg",
        "all_metrics": charts_dir / "all_group_metric_comparison.svg",
        "per_source": charts_dir / "per_source_graph_fusion_target.svg",
        "hardware": charts_dir / "hardware_candidate_false_alarm.svg",
        "distribution": charts_dir / "graph_fusion_prediction_distribution.svg",
    }
    chart_paths["silver"].write_text(build_silver_metrics_svg(summary), encoding="utf-8")
    chart_paths["all_metrics"].write_text(build_all_group_metrics_svg(summary), encoding="utf-8")
    chart_paths["per_source"].write_text(build_per_source_svg(per_source), encoding="utf-8")
    chart_paths["hardware"].write_text(build_hardware_svg(summary), encoding="utf-8")
    chart_paths["distribution"].write_text(build_prediction_distribution_svg(summary), encoding="utf-8")

    html = build_html_report(experiment_dir, summary, chart_paths)
    output = experiment_dir / "visual_report.html"
    output.write_text(html, encoding="utf-8")
    print(f"已写入可视化报告: {output}")
    print(f"已写入 SVG 图表: {charts_dir}")
    return 0


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def decimal(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):.4f}"


def display_target(target: str) -> str:
    return DISPLAY_TARGET_LABELS.get(target, target)


def svg_header(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
        "<style>"
        "text{font-family:Arial,'Microsoft YaHei',sans-serif;fill:#263238}"
        ".title{font-size:22px;font-weight:700}.subtitle{font-size:13px;fill:#6f7b83}"
        ".axis{font-size:12px;fill:#6f7b83}.label{font-size:13px}.value{font-size:12px;fill:#263238}"
        "</style>"
    )


def axis_grid(x: int, y: int, width: int, height: int, ticks: int = 5) -> str:
    parts = []
    for i in range(ticks + 1):
        ratio = i / ticks
        px = x + ratio * width
        value = int(ratio * 100)
        parts.append(f'<line x1="{px:.1f}" y1="{y}" x2="{px:.1f}" y2="{y + height}" stroke="{PALETTE["grid"]}" />')
        parts.append(f'<text class="axis" x="{px:.1f}" y="{y + height + 22}" text-anchor="middle">{value}%</text>')
    return "\n".join(parts)


def build_silver_metrics_svg(summary: dict[str, Any]) -> str:
    width, height = 980, 430
    metrics = [
        "fault_origin_accuracy",
        "target_accuracy",
        "top3_target_accuracy",
        "target_macro_f1",
        "serviceability_type_accuracy",
    ]
    rule = summary["silver_test_rule_weighted"]
    graph = summary["silver_test_graph_fusion"]
    x0, y0, chart_w = 250, 88, 620
    row_h, bar_h = 58, 17
    parts = [svg_header(width, height)]
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    parts.append('<text class="title" x="36" y="42">银标签主实验：方法对比</text>')
    parts.append('<text class="subtitle" x="36" y="66">BGL 官方告警边界评测，共 400 个样本，数值越高越好。</text>')
    parts.append(axis_grid(x0, y0, chart_w, row_h * len(metrics)))
    for idx, metric in enumerate(metrics):
        y = y0 + idx * row_h + 12
        parts.append(f'<text class="label" x="36" y="{y + 16}">{escape(METRIC_LABELS[metric])}</text>')
        for offset, label, data, color in [
            (0, "Rule", rule, PALETTE["rule"]),
            (22, "Graph", graph, PALETTE["graph"]),
        ]:
            value = float(data.get(metric) or 0)
            bar_w = chart_w * min(value, 1)
            parts.append(f'<rect x="{x0}" y="{y + offset}" width="{bar_w:.1f}" height="{bar_h}" rx="3" fill="{color}"/>')
            parts.append(f'<text class="value" x="{x0 + bar_w + 8:.1f}" y="{y + offset + 13}">{value * 100:.1f}%</text>')
    parts.append(f'<rect x="745" y="34" width="14" height="14" fill="{PALETTE["rule"]}"/><text class="axis" x="766" y="46">规则加权</text>')
    parts.append(f'<rect x="745" y="56" width="14" height="14" fill="{PALETTE["graph"]}"/><text class="axis" x="766" y="68">图融合</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def build_all_group_metrics_svg(summary: dict[str, Any]) -> str:
    width, height = 1100, 500
    groups = ["silver_test", "weak_test", "mixed_test"]
    metrics = ["fault_origin_accuracy", "target_accuracy", "target_macro_f1", "top3_target_accuracy"]
    x0, y0 = 70, 94
    group_w, max_h = 320, 300
    bar_w = 26
    parts = [svg_header(width, height), '<rect width="100%" height="100%" fill="#ffffff"/>']
    parts.append('<text class="title" x="36" y="42">三组实验关键指标</text>')
    parts.append('<text class="subtitle" x="36" y="66">图融合在弱标签一致性上较强，但银标签主实验仍是主要评测依据。</text>')
    for gi, group in enumerate(groups):
        gx = x0 + gi * group_w
        parts.append(f'<text class="label" x="{gx + 80}" y="{y0 - 18}" text-anchor="middle">{escape(SPLIT_LABELS[group])}</text>')
        parts.append(f'<line x1="{gx}" y1="{y0 + max_h}" x2="{gx + 245}" y2="{y0 + max_h}" stroke="{PALETTE["grid"]}"/>')
        for mi, metric in enumerate(metrics):
            rule = float(summary[f"{group}_rule_weighted"].get(metric) or 0)
            graph = float(summary[f"{group}_graph_fusion"].get(metric) or 0)
            bx = gx + mi * 58
            for value, color, dx in [(rule, PALETTE["rule"], 0), (graph, PALETTE["graph"], bar_w + 4)]:
                bh = max_h * min(value, 1)
                parts.append(f'<rect x="{bx + dx}" y="{y0 + max_h - bh:.1f}" width="{bar_w}" height="{bh:.1f}" rx="3" fill="{color}"/>')
            parts.append(
                f'<text class="axis" x="{bx + bar_w + 2}" y="{y0 + max_h + 19}" '
                f'text-anchor="middle">{escape(short_metric(metric))}</text>'
            )
        for tick in [0, 0.5, 1.0]:
            y = y0 + max_h - tick * max_h
            parts.append(f'<line x1="{gx - 8}" y1="{y:.1f}" x2="{gx + 245}" y2="{y:.1f}" stroke="{PALETTE["grid"]}" opacity="0.7"/>')
            parts.append(f'<text class="axis" x="{gx - 16}" y="{y + 4:.1f}" text-anchor="end">{int(tick * 100)}%</text>')
    parts.append(f'<rect x="835" y="34" width="14" height="14" fill="{PALETTE["rule"]}"/><text class="axis" x="856" y="46">规则加权</text>')
    parts.append(f'<rect x="835" y="56" width="14" height="14" fill="{PALETTE["graph"]}"/><text class="axis" x="856" y="68">图融合</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def short_metric(metric: str) -> str:
    return {
        "fault_origin_accuracy": "边界",
        "target_accuracy": "目标",
        "target_macro_f1": "Macro-F1",
        "top3_target_accuracy": "Top-3",
    }[metric]


def build_per_source_svg(per_source: dict[str, Any]) -> str:
    data = per_source["mixed_test_graph_fusion"]
    rows = sorted(
        ((source.replace("loghub2k_", ""), metrics["target_accuracy"], metrics["target_macro_f1"]) for source, metrics in data.items()),
        key=lambda item: item[1],
    )
    width, height = 1050, 670
    x0, y0, chart_w = 250, 80, 650
    row_h = 38
    parts = [svg_header(width, height), '<rect width="100%" height="100%" fill="#ffffff"/>']
    parts.append('<text class="title" x="36" y="42">图融合分数据源表现</text>')
    parts.append('<text class="subtitle" x="36" y="64">混合测试集上的根因目标准确率与 Macro-F1，低柱表示该数据源需要重点校准。</text>')
    parts.append(axis_grid(x0, y0, chart_w, row_h * len(rows), ticks=5))
    for idx, (source, acc, macro_f1) in enumerate(rows):
        y = y0 + idx * row_h + 8
        color = PALETTE["red"] if acc < 0.75 else PALETTE["amber"] if acc < 0.9 else PALETTE["green"]
        parts.append(f'<text class="label" x="36" y="{y + 16}">{escape(source)}</text>')
        parts.append(f'<rect x="{x0}" y="{y}" width="{chart_w * acc:.1f}" height="15" rx="3" fill="{color}"/>')
        parts.append(f'<rect x="{x0}" y="{y + 18}" width="{chart_w * macro_f1:.1f}" height="8" rx="2" fill="{PALETTE["blue"]}" opacity="0.65"/>')
        parts.append(f'<text class="value" x="{x0 + chart_w * acc + 8:.1f}" y="{y + 13}">{acc * 100:.1f}%</text>')
    parts.append(f'<rect x="780" y="34" width="14" height="14" fill="{PALETTE["green"]}"/><text class="axis" x="801" y="46">目标准确率</text>')
    parts.append(f'<rect x="780" y="56" width="14" height="8" fill="{PALETTE["blue"]}" opacity="0.65"/><text class="axis" x="801" y="64">Macro-F1</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def build_hardware_svg(summary: dict[str, Any]) -> str:
    width, height = 820, 390
    items = []
    for group in ["silver_test", "weak_test", "mixed_test"]:
        dist = summary[f"{group}_graph_fusion"].get("prediction_distribution", {})
        hardware_count = sum(int(dist.get(target, 0)) for target in HARDWARE_TARGETS)
        case_count = int(summary[f"{group}_graph_fusion"].get("case_count", 0))
        items.append((SPLIT_LABELS[group], hardware_count, case_count, hardware_count / case_count if case_count else 0))
    x0, y0, chart_w = 230, 96, 470
    row_h = 72
    max_rate = max(rate for _, _, _, rate in items) or 1
    parts = [svg_header(width, height), '<rect width="100%" height="100%" fill="#ffffff"/>']
    parts.append('<text class="title" x="36" y="42">硬件候选误报统计</text>')
    parts.append('<text class="subtitle" x="36" y="66">日志证据实验中，图融合输出为硬件或 FRU 候选的样本数量。</text>')
    for idx, (label, count, total, rate) in enumerate(items):
        y = y0 + idx * row_h
        bar_w = chart_w * (rate / max_rate if max_rate else 0)
        parts.append(f'<text class="label" x="36" y="{y + 22}">{escape(label)}</text>')
        parts.append(f'<rect x="{x0}" y="{y}" width="{bar_w:.1f}" height="28" rx="4" fill="{PALETTE["red"]}"/>')
        parts.append(f'<text class="value" x="{x0 + bar_w + 10:.1f}" y="{y + 20}">{count}/{total} ({rate * 100:.2f}%)</text>')
    parts.append('<text class="subtitle" x="36" y="330">解释：这些样本说明，在推荐 FRU 前需要增加软件日志场景的边界门控。</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def build_prediction_distribution_svg(summary: dict[str, Any]) -> str:
    dist = summary["mixed_test_graph_fusion"]["prediction_distribution"]
    items = sorted(dist.items(), key=lambda item: item[1], reverse=True)
    width, height = 960, 460
    x0, y0, chart_w = 260, 82, 560
    row_h = 42
    max_count = max(count for _, count in items)
    parts = [svg_header(width, height), '<rect width="100%" height="100%" fill="#ffffff"/>']
    parts.append('<text class="title" x="36" y="42">图融合预测分布</text>')
    parts.append('<text class="subtitle" x="36" y="64">混合测试集输出分布，硬件类标签用红色标出。</text>')
    for idx, (target, count) in enumerate(items):
        y = y0 + idx * row_h
        color = PALETTE["red"] if target in HARDWARE_TARGETS else PALETTE["green"] if target == "none" else PALETTE["blue"]
        bar_w = chart_w * count / max_count
        parts.append(f'<text class="label" x="36" y="{y + 18}">{escape(display_target(target))}</text>')
        parts.append(f'<rect x="{x0}" y="{y}" width="{bar_w:.1f}" height="24" rx="4" fill="{color}"/>')
        parts.append(f'<text class="value" x="{x0 + bar_w + 8:.1f}" y="{y + 17}">{count}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def build_html_report(experiment_dir: Path, summary: dict[str, Any], chart_paths: dict[str, Path]) -> str:
    chart_imgs = "\n".join(
        f'<section class="chart"><img src="charts/{escape(path.name)}" alt="{escape(name)} 图表"></section>'
        for name, path in chart_paths.items()
    )
    rows = []
    for group in ["silver_test", "weak_test", "mixed_test"]:
        for method in ["rule_weighted", "graph_fusion"]:
            key = f"{group}_{method}"
            item = summary[key]
            rows.append(
                "<tr>"
                f"<td>{escape(SPLIT_LABELS[group])}</td>"
                f"<td>{escape(METHOD_LABELS[method])}</td>"
                f"<td>{item['case_count']}</td>"
                f"<td>{pct(item['fault_origin_accuracy'])}</td>"
                f"<td>{pct(item['target_accuracy'])}</td>"
                f"<td>{pct(item['top3_target_accuracy'])}</td>"
                f"<td>{pct(item['target_macro_f1'])}</td>"
                f"<td>{pct(item['serviceability_type_accuracy'])}</td>"
                "</tr>"
            )
    silver_graph = summary["silver_test_graph_fusion"]
    silver_rule = summary["silver_test_rule_weighted"]
    mixed_graph = summary["mixed_test_graph_fusion"]
    dataset_path = Path("datasets/processed/diagnosis_v3_loghub2k")
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>故障诊断实验结果可视化</title>
  <style>
    :root {{
      --ink: #263238;
      --muted: #6f7b83;
      --line: #d9dee3;
      --panel: #f7f8fa;
      --paper: #ffffff;
      --green: #287c71;
      --blue: #3f6ea8;
      --amber: #c98424;
      --red: #b84e4e;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #eef1f4;
      font-family: Arial, "Microsoft YaHei", sans-serif;
      line-height: 1.5;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 30px 24px 56px;
    }}
    header {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px 28px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 28px 0 12px;
      font-size: 19px;
      letter-spacing: 0;
    }}
    .subtle {{
      color: var(--muted);
      margin: 0;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .kpi {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
      background: var(--panel);
    }}
    .kpi strong {{
      display: block;
      font-size: 26px;
      line-height: 1.1;
    }}
    .kpi span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
    }}
    .chart {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      overflow-x: auto;
    }}
    .chart img {{
      width: 100%;
      min-width: 720px;
      height: auto;
      display: block;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 14px;
    }}
    th {{
      background: #edf1f5;
      color: #37474f;
      font-weight: 700;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
    .notes {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px 18px;
    }}
    .notes li {{
      margin: 7px 0;
    }}
    .problem-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .problem {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 16px;
    }}
    .problem strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 15px;
    }}
    .problem p {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    code {{
      background: #edf1f5;
      padding: 2px 5px;
      border-radius: 4px;
    }}
    @media (max-width: 860px) {{
      .kpis, .grid, .problem-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>故障诊断实验结果可视化</h1>
    <p class="subtle">数据集：<code>{escape(str(dataset_path))}</code></p>
    <div class="kpis">
      <div class="kpi"><strong>28,000</strong><span>处理后样本总数</span></div>
      <div class="kpi"><strong>400</strong><span>银标签主测试样本</span></div>
      <div class="kpi"><strong>{pct(silver_graph['target_accuracy'])}</strong><span>图融合主实验目标准确率</span></div>
      <div class="kpi"><strong>{pct(mixed_graph['top3_target_accuracy'])}</strong><span>图融合混合测试 Top-3</span></div>
    </div>
  </header>

  <h2>核心结论</h2>
  <ul class="notes">
    <li>本实验首先面向电子设备故障诊断中的实际问题：用户只看到故障现象，维修侧需要从有限证据中判断是软件、配置、外部环境还是硬件边界问题。</li>
    <li>当前 Loghub-2k 处理后数据主要覆盖日志/trace 证据，因此本轮实验验证的是“软件层证据驱动的故障边界识别、根因候选排序和硬件误报抑制”这一子问题。</li>
    <li>图融合方法明显优于规则加权方法，尤其在根因目标准确率与 Top-3 根因覆盖率上差距很大。</li>
    <li>主实验应优先看银标签主测试集：图融合的根因目标准确率为 {pct(silver_graph['target_accuracy'])}，规则基线为 {pct(silver_rule['target_accuracy'])}。</li>
    <li>弱标签实验结果较高，主要代表与弱规则标签的一致性，不能直接当成真实根因准确率。</li>
    <li>图融合仍有少量硬件候选误报，后续需要加入软件日志场景的硬件 FRU 抑制门控。</li>
  </ul>

  <h2>实验要解决的实际问题</h2>
  <div class="problem-grid">
    <section class="problem">
      <strong>现象到根因的转换</strong>
      <p>电子设备故障通常以蓝屏、启动失败、联网异常、应用报错等现象出现，实验关注如何从日志证据中形成可解释的根因候选。</p>
    </section>
    <section class="problem">
      <strong>软硬件边界判断</strong>
      <p>日志异常容易被粗糙规则误判为驱动或硬件更换，实验重点观察硬件候选误报，并验证图融合是否能降低错误维修导向。</p>
    </section>
    <section class="problem">
      <strong>证据不足下的诊断可信度</strong>
      <p>当前数据主要是日志/trace，缺少指标、主动测试和维修闭环，因此主结论以银标签测试为准，弱标签只作为辅助一致性分析。</p>
    </section>
  </div>

  <h2>指标总表</h2>
  <table>
    <thead>
      <tr>
        <th>实验组</th><th>方法</th><th>样本数</th><th>边界准确率</th><th>目标准确率</th><th>Top-3 覆盖率</th><th>目标 Macro-F1</th><th>服务性准确率</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>

  <h2>图表</h2>
  <div class="grid">
    {chart_imgs}
  </div>
</main>
</body>
</html>
"""
    return html


if __name__ == "__main__":
    raise SystemExit(main())
