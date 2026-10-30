# 电子设备故障诊断研究原型

[![Stars](https://img.shields.io/github/stars/JINRONG121312/electronic-device-fault-diagnosis?style=flat-square&color=4b97dd)](https://github.com/JINRONG121312/electronic-device-fault-diagnosis/stargazers)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-ffb26b?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square)](#%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-8e8e93?style=flat-square)](#)
[![Status](https://img.shields.io/badge/status-research%20prototype-f0a500?style=flat-square)](#%E8%BE%B9%E7%95%8C%E4%B8%8E%E7%8A%B6%E6%80%81)
[![Series](https://img.shields.io/badge/series-3%20posts-4b97dd?style=flat-square)](docs/series)

> 一台电脑出问题，维修店说"换主板"——但它可能只是驱动装错了。
>
> 这个项目想做的，是把"换哪个件"往后放一格，先回答**故障到底出在软件栈的哪一层**。

面向计算机设备的**软件层故障诊断**研究原型：把日志、指标、设备清单、崩溃转储、主动测试和维修结果统一成可复现的证据，输出可解释的根因候选、边界判断和下一步采集建议。带一个本地 Web 工作台，支持**自机检测**与**互机诊断**。

---

## 它解决什么问题

传统维修流程从"症状"直接跳到"换件"，中间缺了一层归因：

```
蓝屏 → 怀疑内存 → 换内存 → 还是蓝屏
```

本项目把这一步拆开：

```
故障现象
  → 证据标准化（Evidence Schema）
  → 异常检测（健康度）
  → 故障分类（driver / os / firmware / configuration / external / hardware / mixed）
  → 软硬件边界判断（software_side / hardware_side / boundary / uncertain）
  → 故障决策（软件修复 / 配置修复 / 固件处理 / 边界区分测试 / 硬件确认 / 继续补采）
```

FRU（可更换模块）在这个框架里**只是一张维修服务标签**，不是故障分类——因为它描述的是"怎么修"，不是"哪里坏"。

## 两种使用姿态

| 模式 | 场景 | 做法 |
|---|---|---|
| **自机检测** | 本机还能跑程序 | 扫描设备画像 → 采集 `runtime_info.json` → 本地诊断 |
| **互机诊断** | 用一台机器诊断另一台 | Target Agent 远程采集 / 导入离线证据 / 不可交互时的现场指导 |

## 快速开始

```powershell
# 启动本地工作台
powershell -ExecutionPolicy Bypass -File scripts\start_web_server.ps1
# 或
python main.py --host 127.0.0.1 --port 8780
```

浏览器打开 <http://localhost:8780/>（注意：`/api/health` 是 JSON 接口，不是页面）。

互机诊断时，在被诊断机器上起 Target Agent：

```powershell
python target_agent.py --host 0.0.0.0 --port 8790 --token lab-token
```

```powershell
# 跑测试
python -m unittest discover -s tests
```

## 目录

```
fault_diagnosis/   研究入口：证据融合、分类、边界判断、决策
fru_diagnosis/     兼容层：设备画像、服务性对象、历史 FRU 配置
knowledge/         本体、规则、信号目录、中文解释库
configs/           设备画像（机型/OS/采集项）
scripts/           Windows 侧采集脚本（事件日志、崩溃证据、硬件清单）
web/               本地诊断工作台（原生 JS，无构建）
docs/              设计、实验、复现报告与使用手册
  series/          项目复盘系列文章（可直接当博客发）
experiments/       基线方法、评估脚本、公开数据集复现入口
data/              样例证据（runtime_info.json）
```

## 系列文章

1. [为什么我要让电脑自己看病](docs/series/01-why.md)
2. [自机检测：让机器自己说清楚它怎么了](docs/series/02-self-check.md)
3. [互机诊断：用一台电脑给另一台看病](docs/series/03-remote.md)

## 边界与状态

- 这是**研究原型**，不是产品；结论需要人复核。
- 未集成 WinDbg `!analyze -v`，dump 目前只取元数据与关联事件。
- 证据融合权重与 Next-Best-Test 的收益/成本参数需要用真实维修案例校准。
- 数据集（RCAEval / LogHub / GAIA 等）体积较大，未入库，按 `docs/` 里的说明自行下载。

## 许可

采用 **[PolyForm Noncommercial License 1.0.0](LICENSE)**：个人、学习、科研与公益使用免费；**商业用途需另行授权**。

> 严格说是「源码公开的非商业许可」（source-available），不是 OSI 定义的开源许可。
>
> 论文引用、课程作业、二次研究都欢迎，注明出处即可。
