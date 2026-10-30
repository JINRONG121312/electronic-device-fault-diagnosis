# Target Agent 安装与使用说明书

## 1. 作用说明

Target Agent 是运行在**被诊断机器**上的轻量证据采集代理。诊断机不需要安装 Target Agent，诊断机只需要运行本项目 Web 工作台，然后通过 HTTP API 连接被诊断机器上的 Target Agent。

典型结构：

```text
诊断机 Controller
  运行 fru_web_server.py / Web 工作台
  浏览器打开 http://localhost:8780/

被诊断机器 Target
  运行 target_agent.py
  对外提供 /api/health、/api/capabilities、/api/collect
```

适用场景：

- 被诊断机器还能进入 Windows 或 Linux 系统。
- 被诊断机器和诊断机处于同一局域网，或两者网络可达。
- 需要从另一台机器采集设备信息、日志、运行指标、主动测试状态和崩溃转储元数据。

不适用场景：

- 被诊断机器已经断电、无法开机。
- 被诊断机器无法进入系统。
- 被诊断机器无法运行 Python。

这些情况应使用“离线证据导入”或“无法交互现场指导”模式。

## 2. 环境要求

Target Agent 只使用 Python 标准库，不需要额外安装第三方依赖。

要求：

- Python 3.9 或更高版本。
- 被诊断机器可以访问 `target_agent.py` 文件。
- 诊断机能够访问被诊断机器的 IP 和端口。
- 推荐在隔离局域网中使用，不要暴露到公网。

默认端口：

```text
8790
```

默认接口：

```text
/api/health
/api/capabilities
/api/collect
```

## 3. 文件准备

将项目中的 `target_agent.py` 复制到被诊断机器。

如果两台机器在同一项目目录中，可以直接在项目根目录运行。

如果需要单独复制，只需要复制这个文件：

```text
target_agent.py
```

## 4. Windows 安装与启动

### 4.1 检查 Python

在被诊断 Windows 机器上打开 PowerShell：

```powershell
python --version
```

或：

```powershell
py --version
```

如果没有 Python，需要先安装 Python 3.9 以上版本，并确保加入 PATH。

### 4.2 启动 Target Agent

进入 `target_agent.py` 所在目录：

```powershell
cd D:\workspace\code\project
```

使用 Token 启动：

```powershell
python target_agent.py --host 0.0.0.0 --port 8790 --token lab-token
```

或使用环境变量保存 Token：

```powershell
$env:TARGET_AGENT_TOKEN="lab-token"
python target_agent.py --host 0.0.0.0 --port 8790
```

启动成功后会显示：

```text
Target evidence agent running at http://0.0.0.0:8790/
```

### 4.3 Windows 防火墙放行端口

如果诊断机无法连接，被诊断 Windows 机器可能需要放行端口。

以管理员身份打开 PowerShell：

```powershell
New-NetFirewallRule `
  -DisplayName "Fault Diagnosis Target Agent 8790" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8790 `
  -Action Allow
```

### 4.4 Windows 权限说明

普通权限可以采集一部分信息，但以下内容可能需要管理员权限：

- 部分系统事件日志
- 崩溃转储文件元数据
- 电池报告或硬件状态
- 部分设备管理器信息

如果采集结果中出现权限警告，建议以管理员身份启动 PowerShell 后再运行 Target Agent。

## 5. Linux 安装与启动

### 5.1 检查 Python

在被诊断 Linux 机器上执行：

```bash
python3 --version
```

如果没有 Python：

Debian / Ubuntu：

```bash
sudo apt update
sudo apt install -y python3
```

Fedora：

```bash
sudo dnf install -y python3
```

Arch Linux：

```bash
sudo pacman -S python
```

### 5.2 启动 Target Agent

进入 `target_agent.py` 所在目录：

```bash
cd /path/to/project
```

使用 Token 启动：

```bash
python3 target_agent.py --host 0.0.0.0 --port 8790 --token lab-token
```

或使用环境变量：

```bash
export TARGET_AGENT_TOKEN=lab-token
python3 target_agent.py --host 0.0.0.0 --port 8790
```

### 5.3 Linux 防火墙放行端口

Ubuntu / Debian 使用 UFW：

```bash
sudo ufw allow 8790/tcp
```

firewalld：

```bash
sudo firewall-cmd --add-port=8790/tcp --permanent
sudo firewall-cmd --reload
```

### 5.4 Linux 权限说明

普通用户可以采集部分基础信息，但以下内容可能需要 root 权限：

- `journalctl` 中的部分系统日志
- `dmesg` 内核日志
- SMART 数据
- 硬件传感器
- DMI 序列号

如果需要更完整证据，可以使用：

```bash
sudo python3 target_agent.py --host 0.0.0.0 --port 8790 --token lab-token
```

## 6. 在诊断机测试连接

假设被诊断机器 IP 是：

```text
192.168.1.50
```

### 6.1 PowerShell 测试

在诊断机执行：

```powershell
Invoke-RestMethod `
  -Uri "http://192.168.1.50:8790/api/health" `
  -Headers @{ "X-Agent-Token" = "lab-token" }
```

查询采集能力：

```powershell
Invoke-RestMethod `
  -Uri "http://192.168.1.50:8790/api/capabilities" `
  -Headers @{ "X-Agent-Token" = "lab-token" }
```

### 6.2 curl 测试

Windows、Linux、macOS 均可使用：

```bash
curl -H "X-Agent-Token: lab-token" http://192.168.1.50:8790/api/health
```

查询能力：

```bash
curl -H "X-Agent-Token: lab-token" http://192.168.1.50:8790/api/capabilities
```

## 7. 在 Web 工作台中使用

在诊断机启动主 Web 工作台：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_web_server.ps1
```

浏览器打开：

```text
http://localhost:8780/
```

进入“互机诊断”页面，选择“接口采集”模式。

填写：

```text
Target Agent 地址：http://192.168.1.50:8790
Token：lab-token
系统：Windows 或 Linux
症状：蓝屏、黑屏、无法充电、无法联网等
故障时间：可选
客户描述：可选
```

操作顺序：

1. 点击“测试连接/查询能力”。
2. 确认 Target Agent 已连接。
3. 勾选需要采集的证据层。
4. 点击“远程采集并诊断”。
5. 查看故障分类、软硬件边界判断、候选根因和下一步补采建议。

## 8. Target Agent 可采集内容

Windows 下主要采集：

- 厂商、型号、序列号、BIOS 版本
- PnP 问题设备
- System 事件日志
- 存储、内存、电池、网络指标
- 网络接口
- 崩溃转储元数据：`C:\Windows\Minidump`、`C:\Windows\MEMORY.DMP`

Linux 下主要采集：

- 主机名、系统版本、架构
- DMI 厂商、型号、序列号、BIOS 版本
- `lspci` 设备信息
- `journalctl` 或 `dmesg` 日志
- `/proc/meminfo`
- `lsblk`
- 网络接口
- `/sys/class/thermal` 温度信息

注意：Linux 当前不采集 Windows 风格的 crash dump，因此 `crash_dump` 能力主要适用于 Windows。

## 9. 安全建议

必须使用 Token：

```bash
--token lab-token
```

不要在公网暴露 Target Agent。

仅在隔离实验环境中才允许无 Token 启动：

```bash
python target_agent.py --host 0.0.0.0 --port 8790 --allow-unsafe-no-token
```

不推荐在真实网络环境中使用无 Token 模式。

## 10. 常见问题

### 10.1 诊断机连接不上 Target Agent

检查：

- 被诊断机器是否已经运行 `target_agent.py`
- 启动参数是否为 `--host 0.0.0.0`
- IP 地址是否正确
- 端口是否为 `8790`
- 防火墙是否放行
- Token 是否一致
- 两台机器是否在同一网络或可路由

### 10.2 返回 Unauthorized

说明 Token 不正确或请求未带 Token。

PowerShell 使用：

```powershell
-Headers @{ "X-Agent-Token" = "lab-token" }
```

curl 使用：

```bash
-H "X-Agent-Token: lab-token"
```

### 10.3 采集结果不完整

原因可能是：

- 权限不足
- 某些系统命令不存在
- Linux 没有安装 `journalctl`、`lspci` 或 `lsblk`
- Windows 无法读取部分日志或 dump 文件

此时系统会在 `warnings` 中记录失败原因。诊断层应把这些信息视为“证据不足”，不能当成正常。

### 10.4 蓝屏时 Target Agent 能否工作

蓝屏当场不能工作，因为系统已经停止运行。

可行方式：

- 蓝屏后重启，再运行 Target Agent 采集 dump 元数据。
- 进入安全模式后运行 Target Agent。
- 使用 WinPE 或拆盘方式离线导出 dump。
- 如果机器完全无法启动，只能使用现场指导模式。

项目中蓝屏/死机场景分为四种：

1. 自机重启后诊断：程序运行在已经重启后的本机，采集的是上一次崩溃证据。
2. 互机接口采集诊断：故障机还能运行 Target Agent，由诊断机通过接口采集 `runtime_info` 和 `crash_dump` 元数据。
3. 离线证据导入诊断：通过 WinPE、安全模式或拆盘复制 Minidump、MEMORY.DMP、evtx、驱动列表和 SMART 信息。
4. 无法交互现场指导：无法运行程序也无法读取硬盘时，不扫描 dump，只做现场观察和补采指导。

Target Agent 只覆盖第二种场景；第一种由自机采集脚本完成，第三种由离线导入完成，第四种只提供指导。

## 11. 停止 Target Agent

在运行窗口按：

```text
Ctrl + C
```

即可停止服务。
