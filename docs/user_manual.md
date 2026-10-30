# 电子设备故障诊断研究工作台说明书

## 1. 系统定位

本系统用于电子设备故障诊断研究，重点面向计算机设备的软件层故障、硬件故障以及软硬件边界故障。系统不把蓝屏、黑屏、无法充电等症状单独作为诊断模块，而是将其作为输入症状，再结合日志、指标、设备状态、崩溃转储和主动测试结果进行异常检测、故障分类、边界判断和故障决策。

研究主线是故障诊断。FRU 或可更换模块只作为维修服务标签，用于诊断完成后的维修决策，不作为核心故障分类标签。

## 2. 启动和访问

在项目目录启动 Web 服务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_web_server.ps1
```

浏览器访问：

```text
http://localhost:8780/
```

注意：`http://localhost:8780/api/health` 是 JSON 健康检查接口，不是前端页面。如果浏览器只显示 JSON，说明打开了健康检查接口，应改为打开根路径 `/`。

## 3. 核心诊断流程

系统诊断流程为：

```text
证据采集
-> anomaly_detection 异常检测
-> fault_classification 故障分类
-> boundary_assessment 软硬件边界判断
-> fault_decision 故障决策
-> 维护策略和补采建议
```

各层含义：

- 异常检测：判断当前设备是否存在异常运行状态，并输出健康度。
- 故障分类：判断故障来源，例如驱动、操作系统、固件、配置、外部环境、硬件或混合不确定。
- 软硬件边界判断：判断证据更偏软件侧、硬件侧、软硬件边界或证据不足。
- 故障决策：根据分类和边界判断，输出软件修复、继续补采、边界区分测试、硬件确认测试或服务建议。

## 4. 自机检测

适用场景：本机操作系统仍可运行本程序。

推荐步骤：

1. 打开“自机检测”页面。
2. 点击“扫描本机”，生成或更新设备画像。
3. 点击“采集数据”，更新 `runtime_info.json`。
4. 点击“开始诊断”，查看健康度、异常检测、故障分类、软硬件边界判断和决策结果。
5. 如果提示证据不足，按照“下一步排查”补充主动测试或故障时间窗口日志。

结果解读：

- 健康度用于判断异常是否影响当前运行，不等于最终根因。
- 故障分类是研究主标签，例如 `driver_fault`、`os_fault`、`hardware_fault`。
- 软硬件边界用于判断是否需要先做边界区分测试。
- 可更换模块属于维修服务标签，不等于故障分类标签。

## 5. 互机诊断

互机诊断表示装载本系统的机器作为诊断主机，诊断另一台故障机器。

### 5.1 接口采集模式

适用场景：故障机还能进入系统，并能运行 Target Agent。

在被诊断机器启动 Target Agent：

```powershell
python target_agent.py --host 0.0.0.0 --port 8790 --token lab-token
```

完整 Windows/Linux 部署步骤见 `docs/target_agent_manual.md`。

在诊断主机的“互机诊断”页面填写：

- Target Agent 地址，例如 `http://目标机IP:8790`
- Token
- 厂家、型号、系统类型
- 故障时间、症状和客户描述

然后点击“测试连接/查询能力”，确认可采集证据层；再点击“远程采集并诊断”。

### 5.2 离线证据模式

适用场景：故障机不能联网，但仍能运行采集脚本。

处理方式：

1. 在故障机导出 `runtime_info.json`。
2. 将文件复制到诊断主机。
3. 在互机诊断页粘贴或导入证据。
4. 系统根据离线证据运行同一套诊断流程。

### 5.3 无法交互/现场指导模式

适用场景：故障机断电、无法启动、蓝屏死机后无法运行采集程序。

此时系统只能根据型号、症状和现场观察生成指导。建议记录：

- 电源灯、风扇、蜂鸣码、屏幕文字
- 外接屏测试结果
- 已知正常适配器交叉测试
- 最近硬件、驱动、系统或固件变更
- 照片或视频证据

该模式不应直接给出最终硬件结论，只输出初步判断、补采建议和现场排查步骤。

## 6. 软硬件边界判断

软硬件边界是诊断归因边界，不是物理边界。它描述软件栈控制硬件、硬件状态反馈软件的交互位置。

边界类型：

- `software_side`：驱动、操作系统、配置、文件系统或策略证据强，硬件证据弱。
- `hardware_side`：SMART、WHEA、内存测试、设备缺失或主动测试失败等硬件证据强。
- `hardware_software_boundary`：驱动、固件、总线、控制器、接口证据与硬件路径证据同时存在。
- `mixed_or_uncertain`：只有症状描述、证据不足或多方向证据接近。

当结果为 `hardware_software_boundary` 时，应优先做边界区分测试，而不是直接建议更换硬件。

## 7. 典型故障采证建议

蓝屏/死机：

- Stop code、BugCheck code
- `C:\Windows\Minidump` 或 `MEMORY.DMP` 元数据
- WHEA、Kernel-Power、磁盘、显示和驱动事件
- 近期驱动、系统、固件或安全软件变更

蓝屏场景按采集条件分为四类：

1. 自机重启后诊断：本机蓝屏后已经重启，程序可以运行。系统采集 `C:\Windows\Minidump\*.dmp`、`C:\Windows\MEMORY.DMP` 元数据、BugCheck、WHEA、Kernel-Power、最近驱动/系统更新、问题设备和 SMART/NVMe 状态。此时诊断的是“上一次崩溃”。
2. 互机接口采集诊断：故障机还能进入系统并运行 Target Agent。诊断机连接 Target Agent，查询能力，下发采集任务，获取 `runtime_info` 和 `crash_dump` 元数据后执行诊断。
3. 离线证据导入诊断：故障机不能稳定运行程序，但硬盘还能读取。可从 WinPE、安全模式或拆盘复制 Minidump、MEMORY.DMP、System.evtx、Application.evtx、驱动列表、系统版本和 SMART 信息，再导入诊断机。
4. 无法交互现场指导：故障机不开机、反复蓝屏无法进入系统，或硬盘暂时不可读。此时不做 dump 扫描，只记录 stop code 照片、蓝屏时间、最近驱动/系统/BIOS 变更、是否更换硬件，并建议进入安全模式、WinPE 或拆盘导出证据。

`crash_dump` 是证据层，不是独立诊断模块；蓝屏是 `symptom`。诊断流程仍然是异常检测、故障分类、软硬件边界判断和故障决策。

如果 dump 不存在，系统应记录：

```json
{
  "available": false,
  "reason": "dump_not_found_or_machine_unavailable",
  "next_action": "enable_dump_or_collect_offline_evidence"
}
```

黑屏/无显示：

- 外接屏测试
- BIOS/UEFI 是否可见
- 背光、键盘灯、风扇和 CapsLock 响应
- 显示驱动日志、EDID、面板状态

无法充电：

- 电池健康、循环次数、设计容量和满充容量
- 适配器功率、充电 LED、ACPI/UCSI 事件
- 已知正常适配器、插座和 USB-C 端口交叉测试

无法联网：

- 网卡型号、驱动版本、设备状态
- IP、DNS、网关和信号强度
- 网关 ping、DNS 解析、热点对比
- 蓝牙共存状态

## 8. 证据层

系统统一使用 Evidence Schema 和 `runtime_info.json` 表示证据。

主要证据层：

- `inventory`：厂家、型号、序列号、OS、BIOS、设备管理器/PnP、PCI/USB/块设备。
- `logs`：Windows Event Log、Reliability、journalctl、dmesg、故障时间窗口事件。
- `metrics`：SMART/NVMe、电池、电源、内存、温度、网络、存储延迟。
- `active_tests`：网关 ping、外接屏、适配器交叉测试、存储短测、内存测试等。
- `crash_dump`：BugCheck、minidump/MEMORY.DMP 元数据、WHEA 和 Kernel-Power 关联事件。
- `repair_result`：维修动作、维修后是否解决、最终根因标签。

其中 `repair_result` 对论文实验很重要，用于计算准确率、不必要换件率和维修决策效果。

## 9. 页面功能

- 自机检测：扫描本机、采集运行证据、异常检测、故障分类、边界判断、决策和维护策略。
- 互机诊断：Target Agent 接口采集、离线 runtime_info 诊断、不可交互现场指导。
- 保底采集：按候选故障对象查看最低证据包和缺失项。
- 设置：配置自动刷新、采集路径、历史快照和后台采集。
- 证据明细：查看统一证据字段和原始指标。
- 服务性模型：查看硬件边界、软件/环境根因和可更换性标签。
- 设备接入：选择设备类型、厂家型号并生成诊断画像。
- 数据列表：检索、筛选、排序、分页和批量管理诊断案例。

## 10. 常见问题

只看到 JSON：

- 打开的是 `/api/health`，请访问 `http://localhost:8780/`。

Target Agent 连接失败：

- 检查目标机 IP、端口、Token、防火墙和网络连通性。

采集不完整：

- 部分事件日志、dump、SMART、电池报告或硬件传感器需要管理员权限。

诊断结果为 `mixed_or_uncertain`：

- 表示证据不足或多方向证据接近，需要继续补采。

诊断结果为 `hardware_software_boundary`：

- 表示需要先做边界区分测试，不应直接换件。
