const state = {
  data: null,
  settings: null,
  resolved: null,
  backgroundStatus: null,
  history: [],
  activeView: "self",
  pollTimer: null,
  backgroundPollTimer: null,
  autoRefreshTimer: null,
  autoRefreshEnabled: false,
  dashboardLoading: false,
  actionButton: null,
  experiment: {
    data: null,
    loading: false,
    error: "",
    dataset: "all",
    label: "all",
    split: "test",
    matrixKey: "target",
    limit: 30,
    importing: false,
    importingTest: false,
  },
  records: {
    rows: [],
    loading: false,
    error: "",
    query: "",
    status: "all",
    dateFrom: "",
    dateTo: "",
    sortKey: "createdAt",
    sortDirection: "desc",
    page: 1,
    pageSize: 10,
    selectedIds: new Set(),
  },
};

const AUTO_REFRESH_STORAGE_KEY = "fault_diagnosis_dashboard_auto_refresh";

const viewTitles = {
  self: "自机检测",
  remote: "互机诊断",
  evidence: "标准化证据层",
  baseline: "保底证据采集计划",
  frus: "服务性与硬件边界模型",
  collection: "设置",
  guide: "使用说明",
  setup: "设备接入",
};

const viewSubtitles = {
  self: "扫描当前机器、采集运行证据，并执行异常检测、故障分类和决策。",
  remote: "输入客户可见症状和设备信息，可选导入另一台故障机器的 runtime_info.json。",
  evidence: "统一 runtime_info 字段是跨平台诊断的核心契约。",
  baseline: "按候选故障对象固定最低证据包，明确新设备采什么、缺什么、下一步补什么。",
  frus: "服务性模型描述硬件边界和维修可执行性，FRU 只是其中一种输出标签。",
  collection: "配置仪表盘刷新、数据采集、存储位置、历史快照和后台任务。",
  guide: "说明 Controller-Agent 互机采集、离线导入、不可交互现场指导和各页面功能。",
  setup: "选择设备类型、厂家型号，并生成当前诊断画像。",
};

viewTitles.records = "数据列表";
viewSubtitles.records = "搜索、筛选、排序、分页和批量管理诊断数据。";
viewTitles.experiments = "实验工作台";
viewSubtitles.experiments = "导入测试样本、划分 train/dev/test，并用测试集混淆矩阵量化模型表现。";

const sampleRecords = [
  { id: "r-001", caseId: "CASE-2026-001", device: "ThinkPad T14", fault: "蓝屏死机", status: "diagnosing", createdAt: "2026-05-17", owner: "Li", severity: "high" },
  { id: "r-002", caseId: "CASE-2026-002", device: "Lenovo 81YL", fault: "无法充电", status: "open", createdAt: "2026-05-16", owner: "Wang", severity: "medium" },
  { id: "r-003", caseId: "CASE-2026-003", device: "ASUS FX607JV", fault: "无线网络异常", status: "resolved", createdAt: "2026-05-15", owner: "Chen", severity: "low" },
  { id: "r-004", caseId: "CASE-2026-004", device: "Linux Desktop", fault: "启动失败", status: "blocked", createdAt: "2026-05-12", owner: "Zhao", severity: "high" },
  { id: "r-005", caseId: "CASE-2026-005", device: "Dell Latitude", fault: "黑屏无显示", status: "diagnosing", createdAt: "2026-05-10", owner: "Liu", severity: "high" },
  { id: "r-006", caseId: "CASE-2026-006", device: "HP EliteBook", fault: "系统卡顿", status: "resolved", createdAt: "2026-05-09", owner: "Sun", severity: "low" },
  { id: "r-007", caseId: "CASE-2026-007", device: "ThinkBook 14", fault: "SSD SMART 告警", status: "open", createdAt: "2026-05-08", owner: "Hu", severity: "medium" },
  { id: "r-008", caseId: "CASE-2026-008", device: "Acer Swift", fault: "风扇噪声", status: "diagnosing", createdAt: "2026-05-06", owner: "Gao", severity: "medium" },
  { id: "r-009", caseId: "CASE-2026-009", device: "MacBook Pro", fault: "外接显示异常", status: "blocked", createdAt: "2026-05-04", owner: "Qin", severity: "medium" },
  { id: "r-010", caseId: "CASE-2026-010", device: "Lenovo Legion", fault: "显卡驱动崩溃", status: "resolved", createdAt: "2026-05-01", owner: "Xu", severity: "high" },
  { id: "r-011", caseId: "CASE-2026-011", device: "Surface Laptop", fault: "触控板失灵", status: "open", createdAt: "2026-04-28", owner: "Yang", severity: "low" },
  { id: "r-012", caseId: "CASE-2026-012", device: "Linux Workstation", fault: "内核日志错误", status: "diagnosing", createdAt: "2026-04-25", owner: "Ma", severity: "medium" },
];

const remoteCollectionCatalog = {
  base: {
    id: "case_context",
    title: "设备与故障上下文",
    layer: "inventory",
    priority: "high",
    items: ["厂家、型号、序列号/设备编号", "操作系统、BIOS/固件版本", "故障发生时间、复现频率、触发操作", "客户可见症状和屏幕原文"],
  },
  interface: [
    {
      id: "runtime_bundle",
      title: "可传输证据包",
      layer: "inventory",
      priority: "high",
      items: ["runtime_info.json", "硬件清单、设备管理器/PnP 状态", "驱动、固件、最近更新", "已执行主动测试和维修动作"],
    },
    {
      id: "fault_window_logs",
      title: "故障时间窗口日志",
      layer: "logs",
      priority: "high",
      items: ["System/Application 或 journalctl 日志", "内核、驱动、存储、显示、电源事件", "事件 ID、Provider、级别、时间戳和摘要"],
    },
    {
      id: "device_health_metrics",
      title: "健康指标与主动测试",
      layer: "metrics",
      priority: "medium",
      items: ["SMART/NVMe、坏块、磁盘延迟", "电池、ACPI/UCSI、温度、风扇、内存", "网络、显示、存储、电源主动测试结果"],
    },
  ],
  offline: [
    {
      id: "runtime_bundle",
      title: "离线 runtime_info",
      layer: "inventory",
      priority: "high",
      items: ["runtime_info.json", "故障机系统版本、BIOS、设备清单", "驱动列表、最近更新、设备管理器问题设备", "已尝试维修动作和结果"],
    },
    {
      id: "offline_crash_evidence",
      title: "离线崩溃证据",
      layer: "crash_dump",
      priority: "high",
      items: ["C:\\Windows\\Minidump\\*.dmp 元数据", "C:\\Windows\\MEMORY.DMP 元数据", "System.evtx / Application.evtx 摘要", "WHEA、Kernel-Power、驱动/存储/显示事件"],
    },
    {
      id: "offline_storage_health",
      title: "离线硬件健康证据",
      layer: "metrics",
      priority: "medium",
      items: ["SMART/NVMe 健康状态", "磁盘坏块或文件系统检查结果", "内存测试结果", "WinPE 或拆盘读取到的硬件状态"],
    },
  ],
  power_off: [
    {
      id: "field_observation",
      title: "现场可观察证据",
      layer: "active_tests",
      priority: "high",
      items: ["电源灯、充电灯、适配器灯", "风扇、蜂鸣/闪灯码、键盘背光", "屏幕状态、错误文字、能否进入 BIOS", "照片或短视频"],
    },
    {
      id: "external_isolation",
      title: "外部隔离检查",
      layer: "active_tests",
      priority: "high",
      items: ["已知正常适配器/插座/USB-C 口交叉测试", "外接显示器、移除外设、最小启动", "液体/撞击/异味/过热/松动痕迹"],
    },
  ],
  os: {
    windows: {
      id: "windows_specific",
      title: "Windows 专项证据",
      layer: "logs",
      priority: "high",
      items: ["事件查看器 System/Application", "可靠性监视器、Windows Update 历史", "PnP 问题设备、驱动版本", "蓝屏 dump 元数据、电池报告"],
    },
    linux: {
      id: "linux_specific",
      title: "Linux 专项证据",
      layer: "logs",
      priority: "high",
      items: ["journalctl、dmesg 故障窗口", "lspci、lsusb、lsblk、smartctl", "systemd failed services", "近期 kernel/firmware/DKMS 变更"],
    },
  },
  symptoms: {
    bsod: {
      id: "crash_dump",
      title: "蓝屏/死机证据",
      layer: "crash_dump",
      priority: "high",
      items: ["BugCheck/Stop code", "Minidump 或 MEMORY.DMP 元数据", "WHEA、Kernel-Power、显示/存储/驱动事件", "崩溃前后的驱动和系统变更"],
    },
    black_screen: {
      id: "display_path",
      title: "黑屏/显示路径证据",
      layer: "active_tests",
      priority: "high",
      items: ["外接屏测试", "BIOS 是否有显示", "背光、亮度、合盖状态、EDID", "显示驱动事件和屏幕照片"],
    },
    charging_failure: {
      id: "power_charging",
      title: "电源/充电证据",
      layer: "metrics",
      priority: "high",
      items: ["适配器功率和 LED", "电池健康、循环次数、容量、电压/电流", "ACPI/UCSI/USB-C 事件", "已知正常适配器与接口交叉测试"],
    },
    no_network: {
      id: "network_path",
      title: "网络路径证据",
      layer: "active_tests",
      priority: "medium",
      items: ["网卡型号、驱动、链路和 IP 配置", "网关 ping、DNS、热点/有线对比", "WLAN 服务和设备状态", "蓝牙共存测试"],
    },
    boot_failure: {
      id: "boot_path",
      title: "启动路径证据",
      layer: "logs",
      priority: "high",
      items: ["启动报错原文、蜂鸣/闪灯码", "BIOS 是否识别存储和启动项", "恢复环境日志或内核启动日志", "SSD SMART 和文件系统检查结果"],
    },
    slow_io: {
      id: "performance_io",
      title: "卡顿/性能证据",
      layer: "metrics",
      priority: "medium",
      items: ["磁盘延迟、队列、SMART、坏块", "CPU、内存、温度、风扇、电源模式", "后台服务、杀毒扫描、近期安装", "读写、内存、温度主动测试"],
    },
  },
};

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindActions();
  loadAutoRefreshPreference();
  loadDashboard();
});

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      const view = button.dataset.view;
      if (!view) return;
      state.activeView = view;
      document.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.toggle("active", item.dataset.view === view);
      });
      button.closest(".nav-group")?.setAttribute("open", "");
      document.querySelectorAll(".view").forEach((section) => {
        section.classList.toggle("active", section.id === view);
      });
      document.getElementById("pageTitle").textContent = viewTitles[view] || "故障诊断研究工作台";
      document.getElementById("pageSubtitle").textContent = viewSubtitles[view] || "";
      if (view === "experiments" && !state.experiment.data && !state.experiment.loading) {
        loadExperimentResults();
      }
    });
  });
}

function bindActions() {
  document.getElementById("refreshBtn").addEventListener("click", () => loadDashboard());
  document.getElementById("autoRefreshToggle").addEventListener("change", (event) => {
    setAutoRefresh(event.currentTarget.checked);
  });
  document.getElementById("autoRefreshInterval").addEventListener("change", () => {
    saveAutoRefreshPreference();
    if (state.autoRefreshEnabled) startAutoRefresh();
    updateAutoRefreshStatus();
  });
  document.getElementById("quickScanBtn")?.addEventListener("click", scanFru);
  document.getElementById("quickCollectBtn")?.addEventListener("click", collectRuntime);
  document.getElementById("quickSelfDiagnoseBtn")?.addEventListener("click", runSelfDiagnosis);
  document.getElementById("quickOpenOverviewBtn")?.addEventListener("click", openDiagnosisOverview);
  document.getElementById("setupForm").addEventListener("submit", submitSetup);
  document.getElementById("collectionSettingsForm").addEventListener("submit", saveCollectionSettings);
  document.getElementById("startBackgroundBtn").addEventListener("click", startBackgroundCollection);
  document.getElementById("stopBackgroundBtn").addEventListener("click", stopBackgroundCollection);
  document.getElementById("refreshBackgroundBtn").addEventListener("click", loadSettings);
  document.getElementById("logCollectForm").addEventListener("submit", collectLogsAroundFault);
  document.getElementById("remoteDiagnosisForm").addEventListener("submit", submitRemoteDiagnosis);
  document.getElementById("probeTargetBtn")?.addEventListener("click", probeTargetAgent);
  document.getElementById("collectTargetBtn")?.addEventListener("click", collectTargetEvidence);
  bindRemoteCollectionControls();
  document.getElementById("fruSearch").addEventListener("input", renderFrus);
  document.getElementById("categoryFilter").addEventListener("change", renderFrus);
  bindRecordsPage();
  bindExperimentsPage();
  bindButtonSystem();
  setDefaultFaultTime();
  renderRemoteCollectionModule();
}

function bindExperimentsPage() {
  const dataset = document.getElementById("experimentDatasetFilter");
  const label = document.getElementById("experimentLabelFilter");
  const split = document.getElementById("experimentSplitFilter");
  const matrixKey = document.getElementById("experimentMatrixKey");
  const limit = document.getElementById("experimentLimit");
  const refresh = document.getElementById("experimentRefreshBtn");
  const importBtn = document.getElementById("experimentImportBtn");
  const importTestBtn = document.getElementById("experimentImportTestBtn");
  dataset?.addEventListener("change", () => {
    state.experiment.dataset = dataset.value;
    loadExperimentResults();
  });
  label?.addEventListener("change", () => {
    state.experiment.label = label.value;
    loadExperimentResults();
  });
  split?.addEventListener("change", () => {
    state.experiment.split = split.value;
    loadExperimentResults();
  });
  matrixKey?.addEventListener("change", () => {
    state.experiment.matrixKey = matrixKey.value;
    loadExperimentResults();
  });
  limit?.addEventListener("change", () => {
    state.experiment.limit = Number(limit.value) || 30;
    loadExperimentResults();
  });
  refresh?.addEventListener("click", () => loadExperimentResults());
  importBtn?.addEventListener("click", importExperimentDataset);
  importTestBtn?.addEventListener("click", importExperimentTestDataset);
}

function bindRecordsPage() {
  const bindings = [
    ["recordsSearch", "input", () => updateRecordsFilters({ query: document.getElementById("recordsSearch").value })],
    ["recordsStatus", "change", () => updateRecordsFilters({ status: document.getElementById("recordsStatus").value })],
    ["recordsDateFrom", "change", () => updateRecordsFilters({ dateFrom: document.getElementById("recordsDateFrom").value })],
    ["recordsDateTo", "change", () => updateRecordsFilters({ dateTo: document.getElementById("recordsDateTo").value })],
    ["recordsPageSize", "change", () => updateRecordsFilters({ pageSize: Number(document.getElementById("recordsPageSize").value) || 10 })],
    ["recordsPrevBtn", "click", () => setRecordsPage(state.records.page - 1)],
    ["recordsNextBtn", "click", () => setRecordsPage(state.records.page + 1)],
    ["recordsResetBtn", "click", resetRecordsFilters],
    ["recordsReloadBtn", "click", () => loadRecords()],
    ["recordsErrorBtn", "click", () => loadRecords({ fail: true })],
    ["recordsBulkDeleteBtn", "click", deleteSelectedRecords],
  ];
  bindings.forEach(([id, eventName, handler]) => {
    document.getElementById(id)?.addEventListener(eventName, handler);
  });

  document.getElementById("recordsSelectAll")?.addEventListener("change", (event) => {
    const visibleRows = getRecordsPageRows().rows;
    visibleRows.forEach((row) => {
      if (event.currentTarget.checked) {
        state.records.selectedIds.add(row.id);
      } else {
        state.records.selectedIds.delete(row.id);
      }
    });
    renderRecords();
  });

  document.querySelectorAll(".sort-button").forEach((button) => {
    button.addEventListener("click", () => sortRecords(button.dataset.sortKey));
  });

  document.getElementById("recordsTableBody")?.addEventListener("click", handleRecordTableClick);
  document.getElementById("recordsTableBody")?.addEventListener("change", handleRecordTableChange);
  loadRecords();
}

function bindButtonSystem() {
  document.querySelectorAll("[data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector(`.nav-item[data-view="${button.dataset.viewShortcut}"]`)?.click();
      button.closest(".btn-dropdown")?.removeAttribute("open");
    });
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button || button.classList.contains("nav-item") || button.classList.contains("btn-menu-button")) return;
    state.actionButton = button;
  });

  document.addEventListener("submit", (event) => {
    const submitter = event.submitter || event.target.querySelector("button[type='submit']");
    if (submitter) state.actionButton = submitter;
  }, true);
}

function bindRemoteCollectionControls() {
  const form = document.getElementById("remoteDiagnosisForm");
  if (!form) return;
  form.querySelectorAll('input[name="remote_mode"], input[name="symptoms"], select[name="os_family"]').forEach((control) => {
    control.addEventListener("change", () => {
      updateRemoteModeUi();
      renderRemoteCollectionModule();
    });
  });
  updateRemoteModeUi();
}

async function loadDashboard(options = {}) {
  const { silent = false, fromAuto = false } = options;
  if (state.dashboardLoading && fromAuto) return;
  state.dashboardLoading = true;
  if (!silent) setBusy(true);
  try {
    const data = await dashboardApi.getDashboard();
    state.data = data;
    state.settings = data.collection_settings || state.settings;
    state.backgroundStatus = data.background_status || state.backgroundStatus;
    state.history = data.collection_history || state.history;
    renderAll();
    updateAutoRefreshStatus(new Date());
    if (!silent) showStatus("仪表盘数据已刷新。", "success");
  } catch (error) {
    if (silent) {
      updateAutoRefreshStatus(null, "刷新失败");
    } else {
      showStatus(`加载失败：${error.message}`, "error");
    }
  } finally {
    state.dashboardLoading = false;
    if (!silent) setBusy(false);
  }
}

function loadAutoRefreshPreference() {
  let preference = {};
  try {
    preference = JSON.parse(localStorage.getItem(AUTO_REFRESH_STORAGE_KEY) || "{}");
  } catch (error) {
    preference = {};
  }

  const toggle = document.getElementById("autoRefreshToggle");
  const intervalSelect = document.getElementById("autoRefreshInterval");
  if (intervalSelect && preference.intervalSeconds) {
    intervalSelect.value = String(preference.intervalSeconds);
  }
  if (toggle) {
    toggle.checked = Boolean(preference.enabled);
    setAutoRefresh(toggle.checked, { persist: false });
  }
  updateAutoRefreshStatus();
}

function saveAutoRefreshPreference() {
  const intervalSelect = document.getElementById("autoRefreshInterval");
  const preference = {
    enabled: state.autoRefreshEnabled,
    intervalSeconds: Number(intervalSelect?.value || 30),
  };
  localStorage.setItem(AUTO_REFRESH_STORAGE_KEY, JSON.stringify(preference));
}

function setAutoRefresh(enabled, options = {}) {
  state.autoRefreshEnabled = Boolean(enabled);
  const toggle = document.getElementById("autoRefreshToggle");
  if (toggle) toggle.checked = state.autoRefreshEnabled;

  if (state.autoRefreshEnabled) {
    startAutoRefresh();
  } else {
    stopAutoRefresh();
  }

  if (options.persist !== false) saveAutoRefreshPreference();
  updateAutoRefreshStatus();
}

function startAutoRefresh() {
  stopAutoRefresh();
  const intervalSeconds = getAutoRefreshIntervalSeconds();
  state.autoRefreshTimer = setInterval(() => {
    loadDashboard({ silent: true, fromAuto: true });
  }, intervalSeconds * 1000);
}

function stopAutoRefresh() {
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
}

function getAutoRefreshIntervalSeconds() {
  const value = Number(document.getElementById("autoRefreshInterval")?.value || 30);
  return Number.isFinite(value) && value > 0 ? value : 30;
}

function updateAutoRefreshStatus(refreshedAt = null, label = "") {
  const status = document.getElementById("autoRefreshStatus");
  if (!status) return;
  if (!state.autoRefreshEnabled) {
    status.textContent = "手动";
    return;
  }

  const intervalSeconds = getAutoRefreshIntervalSeconds();
  if (label) {
    status.textContent = label;
  } else if (refreshedAt instanceof Date) {
    status.textContent = `每 ${formatRefreshInterval(intervalSeconds)}，${formatClock(refreshedAt)}`;
  } else {
    status.textContent = `每 ${formatRefreshInterval(intervalSeconds)}`;
  }
}

function formatRefreshInterval(seconds) {
  if (seconds >= 60) return `${Math.round(seconds / 60)} 分钟`;
  return `${seconds} 秒`;
}

function formatClock(date) {
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

async function loadSettings() {
  try {
    const result = await dashboardApi.getSettings();
    updateSettingsState(result);
    renderCollectionSettings();
    showStatus("设置已刷新。", "success");
  } catch (error) {
    showStatus(`设置加载失败：${error.message}`, "error");
  }
}

async function submitSetup(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  body.run_detection = form.elements.run_detection.checked;
  body.allow_mismatch = form.elements.allow_mismatch.checked;

  setBusy(true);
  showStatus("正在生成诊断画像。");
  try {
    const result = await dashboardApi.setupProfile(body);
    state.data = result.dashboard;
    renderAll();
    showStatus("诊断画像已生成。", "success");
  } catch (error) {
    showStatus(`配置失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function scanFru() {
  setBusy(true);
  showStatus("服务性对象扫描任务已启动。");
  try {
    const result = await dashboardApi.scanFru({ no_progress: true });
    pollJob(result.job_id, "服务性对象扫描");
  } catch (error) {
    setBusy(false);
    showStatus(`扫描启动失败：${error.message}`, "error");
  }
}

async function collectRuntime() {
  setBusy(true);
  showStatus("运行数据采集任务已启动。");
  try {
    const result = await dashboardApi.collectRuntime({
      hours: 6,
      max_system_events: 200,
      max_application_events: 50,
    });
    pollJob(result.job_id, "运行数据采集");
  } catch (error) {
    setBusy(false);
    showStatus(`采集启动失败：${error.message}`, "error");
  }
}

async function runSelfDiagnosis() {
  setBusy(true);
  showStatus("正在执行自机诊断。");
  try {
    const result = await dashboardApi.diagnose({
      mode: "self",
      symptom: [],
      description: "quick self diagnosis",
    });
    renderQuickDiagnosisResult(result);
    await loadDashboard({ silent: true });
    showStatus("自机诊断已完成。", "success");
  } catch (error) {
    showStatus(`自机诊断失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

function openDiagnosisOverview() {
  loadDashboard();
}

async function saveCollectionSettings(event) {
  event.preventDefault();
  const body = readCollectionSettingsForm(event.currentTarget);
  setBusy(true);
  showStatus("正在保存设置。");
  try {
    const result = await dashboardApi.saveSettings(body);
    updateSettingsState(result);
    if (result.dashboard) {
      state.data = result.dashboard;
    }
    renderAll();
    showStatus("设置已保存。", "success");
  } catch (error) {
    showStatus(`设置保存失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function startBackgroundCollection() {
  const form = document.getElementById("collectionSettingsForm");
  const settings = readCollectionSettingsForm(form);
  settings.background.enabled = true;
  setBusy(true);
  showStatus("正在启动后台采集。");
  try {
    const result = await dashboardApi.saveSettings(settings);
    updateSettingsState(result);
    renderCollectionSettings();
    showStatus("后台采集已启动。", "success");
  } catch (error) {
    showStatus(`后台采集启动失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function stopBackgroundCollection() {
  setBusy(true);
  showStatus("正在停止后台采集。");
  try {
    const result = await dashboardApi.stopBackground();
    updateSettingsState(result);
    renderCollectionSettings();
    showStatus("后台采集已请求停止。", "success");
  } catch (error) {
    showStatus(`后台采集停止失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function collectLogsAroundFault(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const faultTime = formData.get("fault_time");
  const beforeMinutes = Number(formData.get("before_fault_minutes") || 60);
  const afterMinutes = Number(formData.get("after_fault_minutes") || 15);
  const maxEvents = Number(formData.get("max_events") || 500);

  setBusy(true);
  showStatus("正在按故障时间窗口采集日志。");
  try {
    const result = await dashboardApi.collectRuntime({
      hours: Math.max(1, Math.ceil((beforeMinutes + afterMinutes) / 60)),
      fault_time: faultTime,
      before_fault_minutes: beforeMinutes,
      after_fault_minutes: afterMinutes,
      max_system_events: maxEvents,
      max_application_events: Math.max(50, Math.floor(maxEvents / 3)),
    });
    pollJob(result.job_id, "日志窗口采集");
  } catch (error) {
    setBusy(false);
    showStatus(`日志采集启动失败：${error.message}`, "error");
  }
}

async function submitRemoteDiagnosis(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = buildRemoteDiagnosisBody(form);

  setBusy(true);
  showStatus("正在生成互机诊断。");
  try {
    const result = await dashboardApi.diagnose(body);
    renderRemoteDiagnosisResult(result);
    showStatus("互机诊断已生成。", "success");
  } catch (error) {
    showStatus(`互机诊断失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function probeTargetAgent() {
  const form = document.getElementById("remoteDiagnosisForm");
  if (!form) return;
  const body = buildTargetConnectionBody(form);
  setBusy(true);
  showStatus("正在连接被诊断机器 Target Agent。");
  try {
    const result = await dashboardApi.targetProbe(body);
    renderTargetAgentStatus(result);
    showStatus("Target Agent 连接成功，能力信息已读取。", "success");
  } catch (error) {
    renderTargetAgentStatus({ ok: false, error: error.message });
    showStatus(`Target Agent 连接失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

async function collectTargetEvidence() {
  const form = document.getElementById("remoteDiagnosisForm");
  if (!form) return;
  const body = {
    ...buildRemoteDiagnosisBody(form),
    ...buildTargetConnectionBody(form),
    collect: new FormData(form).getAll("target_collect"),
  };
  setBusy(true);
  showStatus("正在通过 Target Agent 采集证据并运行诊断。");
  try {
    const result = await dashboardApi.targetCollect(body);
    renderTargetAgentStatus({
      ok: true,
      collected: true,
      evidence_package: result.evidence_package,
      target_url: result.target_url,
    });
    renderRemoteDiagnosisResult(result.diagnosis || {});
    showStatus("远程证据采集和互机诊断已完成。", "success");
  } catch (error) {
    renderTargetAgentStatus({ ok: false, error: error.message });
    showStatus(`远程采集失败：${error.message}`, "error");
  } finally {
    setBusy(false);
  }
}

function buildRemoteDiagnosisBody(form) {
  const formData = new FormData(form);
  const body = Object.fromEntries(formData.entries());
  body.symptoms = formData.getAll("symptoms");
  const remoteMode = String(formData.get("remote_mode") || "interface");
  if (remoteMode === "interface") {
    body.mode = "cross_machine_interface";
  } else if (remoteMode === "offline") {
    body.mode = "cross_machine_offline";
  } else if (remoteMode === "power_off") {
    body.mode = "cross_machine_power_off";
  } else {
    body.mode = "cross_machine_remote";
  }
  return body;
}

function buildTargetConnectionBody(form) {
  const formData = new FormData(form);
  return {
    target_url: String(formData.get("target_url") || "").trim(),
    token: String(formData.get("target_token") || "").trim(),
    timeout: Number(formData.get("target_timeout") || 8),
    time_window_minutes: Number(formData.get("time_window_minutes") || 60),
  };
}

function pollJob(jobId, label) {
  if (state.pollTimer) clearInterval(state.pollTimer);

  state.pollTimer = setInterval(async () => {
    try {
      const job = await dashboardApi.getJob(jobId);
      if (job.status === "running") {
        showStatus(`${label}正在运行。`);
        return;
      }

      clearInterval(state.pollTimer);
      state.pollTimer = null;
      setBusy(false);

      if (job.status === "completed") {
        showStatus(`${label}完成，正在刷新数据。`, "success");
        await loadDashboard();
      } else {
        showStatus(`${label}失败：${job.stderr || job.stdout || job.message}`, "error");
      }
    } catch (error) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      setBusy(false);
      showStatus(`任务状态读取失败：${error.message}`, "error");
    }
  }, 1400);
}

function updateSettingsState(result) {
  state.settings = result.settings || state.settings;
  state.resolved = result.resolved || state.resolved;
  state.backgroundStatus = result.background_status || result.status || state.backgroundStatus;
  state.history = result.history || state.history || [];
  if (result.dashboard) {
    state.data = result.dashboard;
  }
}

function loadRecords(options = {}) {
  state.records.loading = true;
  state.records.error = "";
  renderRecords();

  window.setTimeout(() => {
    if (options.fail) {
      state.records.loading = false;
      state.records.error = "数据加载失败，请检查网络或稍后重试。";
      renderRecords();
      return;
    }

    state.records.rows = sampleRecords.map((row) => ({ ...row }));
    state.records.selectedIds.clear();
    state.records.loading = false;
    state.records.page = 1;
    renderRecords();
  }, 350);
}

function updateRecordsFilters(patch) {
  Object.assign(state.records, patch, { page: 1 });
  renderRecords();
}

function resetRecordsFilters() {
  state.records.query = "";
  state.records.status = "all";
  state.records.dateFrom = "";
  state.records.dateTo = "";
  state.records.page = 1;
  ["recordsSearch", "recordsDateFrom", "recordsDateTo"].forEach((id) => {
    const input = document.getElementById(id);
    if (input) input.value = "";
  });
  const status = document.getElementById("recordsStatus");
  if (status) status.value = "all";
  renderRecords();
}

function setRecordsPage(page) {
  const totalPages = getRecordsPageRows().totalPages;
  state.records.page = Math.min(Math.max(1, page), totalPages);
  renderRecords();
}

function sortRecords(sortKey) {
  if (!sortKey) return;
  if (state.records.sortKey === sortKey) {
    state.records.sortDirection = state.records.sortDirection === "asc" ? "desc" : "asc";
  } else {
    state.records.sortKey = sortKey;
    state.records.sortDirection = "asc";
  }
  state.records.page = 1;
  renderRecords();
}

function deleteSelectedRecords() {
  if (!state.records.selectedIds.size) return;
  state.records.rows = state.records.rows.filter((row) => !state.records.selectedIds.has(row.id));
  state.records.selectedIds.clear();
  state.records.page = 1;
  renderRecords();
}

function handleRecordTableClick(event) {
  const button = event.target.closest("[data-record-action]");
  if (!button) return;
  const row = state.records.rows.find((item) => item.id === button.dataset.recordId);
  if (!row) return;

  if (button.dataset.recordAction === "delete") {
    state.records.rows = state.records.rows.filter((item) => item.id !== row.id);
    state.records.selectedIds.delete(row.id);
    renderRecords();
    return;
  }

  if (button.dataset.recordAction === "edit") {
    row.status = row.status === "resolved" ? "diagnosing" : "resolved";
    renderRecords();
    return;
  }

  showStatus(`详情：${row.caseId}，${row.device}，${row.fault}`, "success");
}

function handleRecordTableChange(event) {
  const checkbox = event.target.closest("[data-record-select]");
  if (!checkbox) return;
  if (checkbox.checked) {
    state.records.selectedIds.add(checkbox.dataset.recordSelect);
  } else {
    state.records.selectedIds.delete(checkbox.dataset.recordSelect);
  }
  renderRecords();
}

function getFilteredRecords() {
  const query = state.records.query.trim().toLowerCase();
  return state.records.rows
    .filter((row) => {
      if (state.records.status !== "all" && row.status !== state.records.status) return false;
      if (state.records.dateFrom && row.createdAt < state.records.dateFrom) return false;
      if (state.records.dateTo && row.createdAt > state.records.dateTo) return false;
      if (!query) return true;
      return [row.caseId, row.device, row.fault, row.status, row.createdAt, row.owner]
        .join(" ")
        .toLowerCase()
        .includes(query);
    })
    .sort((a, b) => {
      const key = state.records.sortKey;
      const left = String(a[key] ?? "");
      const right = String(b[key] ?? "");
      const result = left.localeCompare(right, "zh-CN", { numeric: true });
      return state.records.sortDirection === "asc" ? result : -result;
    });
}

function getRecordsPageRows() {
  const rows = getFilteredRecords();
  const totalPages = Math.max(1, Math.ceil(rows.length / state.records.pageSize));
  const page = Math.min(state.records.page, totalPages);
  const start = (page - 1) * state.records.pageSize;
  return {
    rows: rows.slice(start, start + state.records.pageSize),
    filteredRows: rows,
    page,
    totalPages,
  };
}

function renderRecords() {
  const tbody = document.getElementById("recordsTableBody");
  if (!tbody) return;
  const shell = document.getElementById("recordsTableShell");
  const stateBox = document.getElementById("recordsState");
  const bulkBar = document.getElementById("recordsBulkBar");
  const selectedText = document.getElementById("recordsSelectedText");
  const count = document.getElementById("recordsCount");
  const pageText = document.getElementById("recordsPageText");
  const prev = document.getElementById("recordsPrevBtn");
  const next = document.getElementById("recordsNextBtn");
  const selectAll = document.getElementById("recordsSelectAll");

  const { rows, filteredRows, page, totalPages } = getRecordsPageRows();
  state.records.page = page;

  shell.hidden = state.records.loading || Boolean(state.records.error) || !filteredRows.length;
  stateBox.hidden = !(state.records.loading || state.records.error || !filteredRows.length);
  stateBox.className = `data-list-state ${state.records.error ? "error" : ""}`;
  if (state.records.loading) {
    stateBox.innerHTML = `<span class="loading-spinner"></span><strong>正在加载数据...</strong>`;
  } else if (state.records.error) {
    stateBox.innerHTML = `<strong>${escapeHtml(state.records.error)}</strong><button type="button" class="btn btn-secondary btn-sm" onclick="loadRecords()">重试</button>`;
  } else if (!filteredRows.length) {
    stateBox.innerHTML = `<strong>暂无符合条件的数据</strong><span>调整关键词、状态或日期范围后再试。</span>`;
  }

  tbody.innerHTML = rows.map(renderRecordRow).join("");
  renderSortButtons();

  const visibleIds = rows.map((row) => row.id);
  const visibleSelected = visibleIds.filter((id) => state.records.selectedIds.has(id));
  if (selectAll) {
    selectAll.checked = visibleIds.length > 0 && visibleSelected.length === visibleIds.length;
    selectAll.indeterminate = visibleSelected.length > 0 && visibleSelected.length < visibleIds.length;
  }

  if (bulkBar) bulkBar.hidden = state.records.selectedIds.size === 0;
  if (selectedText) selectedText.textContent = `已选择 ${state.records.selectedIds.size} 项`;
  if (count) count.textContent = `${filteredRows.length} 条记录`;
  if (pageText) pageText.textContent = `${page} / ${totalPages}`;
  if (prev) prev.disabled = page <= 1;
  if (next) next.disabled = page >= totalPages;
}

function renderRecordRow(row) {
  return `
    <tr>
      <td class="select-cell"><input type="checkbox" data-record-select="${escapeAttr(row.id)}" ${state.records.selectedIds.has(row.id) ? "checked" : ""} aria-label="选择 ${escapeAttr(row.caseId)}" /></td>
      <td data-label="案例编号"><strong>${escapeHtml(row.caseId)}</strong></td>
      <td data-label="设备">${escapeHtml(row.device)}</td>
      <td data-label="故障类型">${escapeHtml(row.fault)}</td>
      <td data-label="状态">${tag(recordStatusLabel(row.status), recordStatusTone(row.status))}</td>
      <td data-label="日期">${escapeHtml(row.createdAt)}</td>
      <td data-label="负责人">${escapeHtml(row.owner)}</td>
      <td class="row-actions" data-label="操作">
        <button type="button" class="btn btn-secondary btn-xs" data-record-action="detail" data-record-id="${escapeAttr(row.id)}">详情</button>
        <button type="button" class="btn btn-secondary btn-xs" data-record-action="edit" data-record-id="${escapeAttr(row.id)}">编辑</button>
        <button type="button" class="btn btn-danger btn-xs" data-record-action="delete" data-record-id="${escapeAttr(row.id)}">删除</button>
      </td>
    </tr>
  `;
}

function renderSortButtons() {
  document.querySelectorAll(".sort-button").forEach((button) => {
    const active = button.dataset.sortKey === state.records.sortKey;
    button.classList.toggle("active", active);
    button.dataset.direction = active ? state.records.sortDirection : "";
  });
}

function recordStatusLabel(status) {
  const labels = {
    open: "待处理",
    diagnosing: "诊断中",
    resolved: "已解决",
    blocked: "阻塞",
  };
  return labels[status] || status || "-";
}

function recordStatusTone(status) {
  if (status === "resolved") return "green";
  if (status === "blocked") return "red";
  if (status === "diagnosing") return "amber";
  return "gray";
}

function readCollectionSettingsForm(form) {
  const formData = new FormData(form);
  return {
    storage: {
      active_runtime_path: String(formData.get("active_runtime_path") || "").trim(),
      history_dir: String(formData.get("history_dir") || "").trim(),
      filename_template: String(formData.get("filename_template") || "").trim(),
      save_history: form.elements.save_history.checked,
      retention_count: Number(formData.get("retention_count") || 30),
    },
    background: {
      enabled: form.elements.background_enabled.checked,
      interval_minutes: Number(formData.get("interval_minutes") || 30),
      collect_runtime: form.elements.collect_runtime.checked,
      scan_fru: form.elements.scan_fru.checked,
      hours: Number(formData.get("hours") || 6),
      max_system_events: Number(formData.get("max_system_events") || 200),
      max_application_events: Number(formData.get("max_application_events") || 50),
    },
  };
}

async function updateActiveTest(key, value) {
  try {
    const result = await dashboardApi.updateTest({ key, value });
    state.data = result.dashboard;
    renderAll();
    showStatus("主动测试结果已保存。", "success");
  } catch (error) {
    showStatus(`保存失败：${error.message}`, "error");
  }
}

async function loadExperimentResults() {
  state.experiment.loading = true;
  state.experiment.error = "";
  renderExperimentResults();
  try {
    state.experiment.data = await dashboardApi.getLoghubOsExperiment({
      dataset: state.experiment.dataset,
      label: state.experiment.label,
      split: state.experiment.split,
      matrix_key: state.experiment.matrixKey,
      limit: String(state.experiment.limit),
    });
  } catch (error) {
    state.experiment.error = error.message || "实验结果加载失败。";
  } finally {
    state.experiment.loading = false;
    renderExperimentResults();
  }
}

async function importExperimentDataset() {
  const status = document.getElementById("experimentImportStatus");
  const selected = [...document.querySelectorAll('input[name="experimentDataset"]:checked')]
    .map((item) => item.value);
  const windowSize = Number(document.getElementById("experimentWindowSize")?.value || 50);
  const skipDownload = Boolean(document.getElementById("experimentSkipDownload")?.checked);
  state.experiment.importing = true;
  if (status) {
    status.className = "remote-agent-status";
    status.innerHTML = `<strong>正在导入</strong><span>生成数据划分并运行基线预测...</span>`;
  }
  try {
    const data = await dashboardApi.importLoghubOsExperiment({
      datasets: selected,
      window_size: windowSize,
      skip_download: skipDownload,
    });
    if (data.ok === false) {
      throw new Error(`${data.stage || "import"} failed: ${data.stderr || data.stdout || "unknown error"}`);
    }
    state.experiment.data = data;
    if (status) {
      status.className = "remote-agent-status success";
      status.innerHTML = `<strong>导入完成</strong><span>${escapeHtml((data.import?.datasets || []).join(", "))} / window ${escapeHtml(data.import?.window_size || windowSize)}</span>`;
    }
  } catch (error) {
    if (status) {
      status.className = "remote-agent-status error";
      status.innerHTML = `<strong>导入失败</strong><span>${escapeHtml(error.message)}</span>`;
    }
  } finally {
    state.experiment.importing = false;
    renderExperimentResults();
  }
}

async function importExperimentTestDataset() {
  const fileInput = document.getElementById("experimentTestFile");
  const status = document.getElementById("experimentTestImportStatus");
  const file = fileInput?.files?.[0];
  if (!file) {
    if (status) {
      status.className = "remote-agent-status error";
      status.innerHTML = `<strong>未选择文件</strong><span>请选择 DatasetCase JSONL 文件后再导入。</span>`;
    }
    return;
  }

  state.experiment.importingTest = true;
  if (status) {
    status.className = "remote-agent-status";
    status.innerHTML = `<strong>正在上传</strong><span>${escapeHtml(file.name)} 将作为 test split 评估。</span>`;
  }

  try {
    const content = await file.text();
    const data = await dashboardApi.importLoghubOsTestCases({
      filename: file.name,
      content,
    });
    if (data.ok === false) {
      throw new Error(data.error || data.stderr || data.stdout || "uploaded test import failed");
    }
    state.experiment.data = data;
    state.experiment.dataset = "imported_test";
    state.experiment.split = "test";
    document.getElementById("experimentDatasetFilter").value = "imported_test";
    document.getElementById("experimentSplitFilter").value = "test";
    if (status) {
      const warnings = data.import?.warnings || [];
      status.className = "remote-agent-status success";
      status.innerHTML = `
        <strong>测试集已导入</strong>
        <span>${escapeHtml(data.import?.filename || file.name)} / ${escapeHtml(data.import?.case_count ?? 0)} cases</span>
        ${warnings.length ? `<small>${escapeHtml(warnings.slice(0, 2).join("；"))}</small>` : ""}
      `;
    }
  } catch (error) {
    if (status) {
      status.className = "remote-agent-status error";
      status.innerHTML = `<strong>测试集导入失败</strong><span>${escapeHtml(error.message)}</span>`;
    }
  } finally {
    state.experiment.importingTest = false;
    renderExperimentResults();
  }
}

function renderExperimentResults() {
  const data = state.experiment.data;
  const notice = document.getElementById("experimentNotice");
  const workflow = document.getElementById("experimentWorkflow");
  const summary = document.getElementById("experimentSummary");
  const datasetStats = document.getElementById("experimentDatasetStats");
  const metrics = document.getElementById("experimentMetrics");
  const splitMetrics = document.getElementById("experimentSplitMetrics");
  const matrix = document.getElementById("experimentConfusionMatrix");
  const classMetrics = document.getElementById("experimentClassMetrics");
  const targetBars = document.getElementById("experimentTargetBars");
  const cases = document.getElementById("experimentCases");
  if (!notice || !workflow || !summary || !datasetStats || !metrics || !splitMetrics || !matrix || !classMetrics || !targetBars || !cases) return;

  if (state.experiment.loading) {
    notice.className = "status-box";
    notice.textContent = "正在加载实验结果...";
    workflow.innerHTML = renderExperimentWorkflow(null);
    summary.innerHTML = "";
    datasetStats.innerHTML = "";
    metrics.innerHTML = "";
    splitMetrics.innerHTML = "";
    matrix.innerHTML = "";
    classMetrics.innerHTML = "";
    targetBars.innerHTML = "";
    cases.innerHTML = `<div class="data-list-state"><div class="loading-spinner"></div><strong>加载中</strong></div>`;
    return;
  }

  if (state.experiment.error) {
    notice.className = "status-box error";
    notice.textContent = state.experiment.error;
    workflow.innerHTML = renderExperimentWorkflow(data);
    cases.innerHTML = `<div class="data-list-state error"><strong>${escapeHtml(state.experiment.error)}</strong></div>`;
    return;
  }

  if (!data) {
    notice.className = "status-box";
    notice.textContent = "切换到实验工作台后会自动加载 Loghub OS 样本；也可以上传已标注 DatasetCase JSONL 作为 test split。";
    workflow.innerHTML = renderExperimentWorkflow(null);
    return;
  }

  const stats = data.stats || {};
  const metric = data.metrics || {};
  const testMetric = data.test_metrics || data.split_metrics?.test || {};
  const weakAbnormal = metric.label_distribution?.non_fru_fault || 0;
  const noFault = metric.label_distribution?.no_fault_observed || 0;
  const matrixData = metric.confusion_matrix || {};
  notice.className = "status-box";
  notice.textContent = `${data.note || "当前展示的是实验用标签。"} 当前量化视图：${data.filters?.split || "test"} / ${data.filters?.matrix_key || "target"}。`;
  workflow.innerHTML = renderExperimentWorkflow(data);
  summary.innerHTML = [
    metricCard("Test 样本", testMetric.case_count ?? 0, `${testMetric.labeled_count ?? 0} labeled / ${testMetric.predicted_count ?? 0} predicted`),
    metricCard("Test 矩阵准确率", formatMetric(testMetric.confusion_matrix?.accuracy), data.filters?.matrix_key || "target"),
    metricCard("当前筛选样本", data.filtered_count ?? 0, `${data.case_count ?? 0} total`),
    metricCard("当前筛选准确率", formatMetric(matrixData.accuracy), data.filters?.split || "test"),
    metricCard("弱异常/正常", `${weakAbnormal}/${noFault}`, "filtered split"),
  ].join("");
  datasetStats.innerHTML = renderExperimentDatasetStats(stats.datasets || {});
  metrics.innerHTML = renderExperimentMetrics(metric);
  splitMetrics.innerHTML = renderExperimentSplitMetrics(data.split_metrics || {});
  matrix.innerHTML = renderConfusionMatrix(matrixData);
  classMetrics.innerHTML = renderClassMetrics(matrixData.per_class || []);
  targetBars.innerHTML = renderBarList(metric.target_distribution || {});
  cases.innerHTML = renderExperimentCasesTable(data.cases || []);
}

function renderExperimentWorkflow(data) {
  const corpus = data?.corpus || {};
  const splitDistribution = corpus.split_distribution || {};
  const testCases = splitDistribution.test || 0;
  const predicted = corpus.predicted_count || 0;
  const filtered = data?.filtered_count || 0;
  const accuracy = data?.metrics?.confusion_matrix?.accuracy;
  const steps = [
    {
      title: "1. 导入样本",
      note: `${corpus.case_count || 0} cases`,
      done: Boolean(corpus.case_count),
    },
    {
      title: "2. 划分测试集",
      note: `test ${testCases}`,
      done: testCases > 0,
    },
    {
      title: "3. 运行基线",
      note: `${predicted} predicted`,
      done: predicted > 0,
    },
    {
      title: "4. 量化矩阵",
      note: `${filtered} rows / ${formatMetric(accuracy)}`,
      done: accuracy !== null && accuracy !== undefined,
    },
  ];
  return steps.map((step) => `
    <div class="experiment-workflow-step ${step.done ? "done" : "pending"}">
      <strong>${escapeHtml(step.title)}</strong>
      <span>${escapeHtml(step.note)}</span>
    </div>
  `).join("");
}

function renderExperimentDatasetStats(datasets) {
  const entries = Object.entries(datasets);
  if (!entries.length) return `<div class="empty">暂无数据集统计。</div>`;
  return entries.map(([key, item]) => `
    <article class="experiment-dataset-card">
      <div class="fru-card-header">
        <div>
          <strong>${escapeHtml(item.display_name || key)}</strong>
          <span class="fru-id">${escapeHtml(item.description || "")}</span>
        </div>
        ${tag(`${escapeHtml(item.case_count ?? 0)} cases`, "blue")}
      </div>
      <div class="kv-grid compact-kv">
        <div class="kv"><span>Rows</span><strong>${escapeHtml(item.raw_rows_processed ?? "-")}</strong></div>
        <div class="kv"><span>Templates</span><strong>${escapeHtml(item.template_count ?? "-")}</strong></div>
        <div class="kv"><span>Official faults</span><strong>${escapeHtml(item.official_fault_count ?? 0)}</strong></div>
      </div>
      <div class="small-note">
        Weak abnormal: ${escapeHtml(item.label_distribution?.non_fru_fault || 0)} /
        split ${escapeHtml(formatDistribution(item.split_distribution || {}))} /
        official label: ${item.official_label_available ? "yes" : "no"}
      </div>
    </article>
  `).join("");
}

function renderExperimentMetrics(metric) {
  const rows = [
    ["样本数", metric.case_count],
    ["有标签", metric.labeled_count],
    ["有预测", metric.predicted_count],
    ["Fault origin acc.", formatMetric(metric.fault_origin_accuracy)],
    ["Target acc.", formatMetric(metric.target_accuracy)],
    ["Macro F1", formatMetric(metric.macro_f1)],
  ];
  return rows.map(([label, value]) => `
    <div class="kv">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value ?? "-")}</strong>
    </div>
  `).join("");
}

function renderExperimentSplitMetrics(splitMetrics) {
  const order = ["train", "dev", "test", "all"];
  return order.map((split) => {
    const item = splitMetrics[split] || {};
    const matrix = item.confusion_matrix || {};
    return `
      <button type="button" class="experiment-split-card ${state.experiment.split === split ? "active" : ""}" onclick="setExperimentSplit('${escapeAttr(split)}')">
        <strong>${escapeHtml(split)}</strong>
        <span>${escapeHtml(item.case_count ?? 0)} cases / ${escapeHtml(item.predicted_count ?? 0)} predicted</span>
        <small>accuracy ${escapeHtml(formatMetric(matrix.accuracy))} · macro-F1 ${escapeHtml(formatMetric(item.macro_f1))}</small>
      </button>
    `;
  }).join("");
}

function setExperimentSplit(split) {
  state.experiment.split = split;
  const select = document.getElementById("experimentSplitFilter");
  if (select) select.value = split;
  loadExperimentResults();
}

function renderConfusionMatrix(matrix) {
  const classes = matrix.classes || [];
  const rows = matrix.rows || [];
  if (!classes.length || !rows.length) return `<div class="empty">当前筛选条件下没有可计算的混淆矩阵。</div>`;
  return `
    <table class="matrix-table">
      <thead>
        <tr>
          <th>期望 \\ 预测</th>
          ${classes.map((klass) => `<th>${escapeHtml(klass)}</th>`).join("")}
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((row) => `
          <tr>
            <th>${escapeHtml(row.expected)}</th>
            ${(row.values || []).map((value, index) => `<td class="${classes[index] === row.expected ? "matrix-hit" : ""}">${escapeHtml(value)}</td>`).join("")}
            <td>${escapeHtml(row.total)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderClassMetrics(items) {
  if (!items.length) return `<div class="empty">暂无分类指标。</div>`;
  return `
    <table class="data-table compact-table">
      <thead>
        <tr>
          <th>类别</th>
          <th>Precision</th>
          <th>Recall</th>
          <th>F1</th>
          <th>Support</th>
        </tr>
      </thead>
      <tbody>
        ${items.map((item) => `
          <tr>
            <td data-label="Class"><strong>${escapeHtml(item.class)}</strong></td>
            <td data-label="Precision">${escapeHtml(formatMetric(item.precision))}</td>
            <td data-label="Recall">${escapeHtml(formatMetric(item.recall))}</td>
            <td data-label="F1">${escapeHtml(formatMetric(item.f1))}</td>
            <td data-label="Support">${escapeHtml(item.support ?? 0)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderExperimentCasesTable(items) {
  if (!items.length) return `<div class="empty">当前筛选条件下没有样本。</div>`;
  return `
    <table class="data-table compact-table">
      <thead>
        <tr>
          <th>Case</th>
          <th>Dataset</th>
          <th>Split</th>
          <th>期望</th>
          <th>预测</th>
          <th>Match</th>
          <th>Signals</th>
        </tr>
      </thead>
      <tbody>
        ${items.map((item) => {
          const expected = item.expected?.[state.experiment.matrixKey] || "-";
          const predicted = item.predicted?.[state.experiment.matrixKey] || "-";
          const matched = expected === predicted;
          const terms = item.signals?.abnormal_terms || [];
          return `
            <tr>
              <td data-label="Case"><strong>${escapeHtml(item.case_id)}</strong><span class="small-label">lines ${escapeHtml(item.line_start)}-${escapeHtml(item.line_end)}</span></td>
              <td data-label="Dataset">${escapeHtml(item.dataset_key)}</td>
              <td data-label="Split">${escapeHtml(item.split)}</td>
              <td data-label="期望">${escapeHtml(expected)}</td>
              <td data-label="预测">${escapeHtml(predicted)}</td>
              <td data-label="Match">${tag(matched ? "match" : "miss", matched ? "green" : "red")}</td>
              <td data-label="Signals">${escapeHtml(terms.slice(0, 4).join(", ") || "none")}</td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
}

function renderExperimentCases(items) {
  if (!items.length) return `<div class="empty">当前筛选条件下没有样本。</div>`;
  return items.map((item) => {
    const prediction = item.prediction || {};
    const signals = item.signals || {};
    const abnormalTerms = signals.abnormal_terms || [];
    const evidenceMessages = item.evidence_messages || [];
    const rawMessages = item.raw_messages || [];
    return `
      <article class="experiment-case-card">
        <div class="fru-card-header">
          <div>
            <strong>${escapeHtml(item.case_id)}</strong>
            <span class="fru-id">${escapeHtml(item.dataset_key)} / ${escapeHtml(item.split)} / lines ${escapeHtml(item.line_start)}-${escapeHtml(item.line_end)}</span>
          </div>
          <div class="chip-row">
            ${tag(experimentLabel(item.fault_origin), item.fault_origin === "non_fru_fault" ? "amber" : "green")}
            ${tag(item.target || "-", item.target === "none" ? "gray" : "blue")}
            ${tag(`confidence ${item.confidence || "-"}`, "gray")}
          </div>
        </div>
        <div class="experiment-case-grid">
          <section>
            <h3>弱标签信号</h3>
            <div class="chip-row">
              ${(abnormalTerms.length ? abnormalTerms : ["none"]).map((term) => tag(term, abnormalTerms.length ? "amber" : "gray")).join("")}
            </div>
            <div class="small-note">Manual review: ${item.manual_review_required ? "required" : "not required"}</div>
          </section>
          <section>
            <h3>基线预测</h3>
            <div class="chip-row">
              ${tag(prediction.fault_origin || "not run", item.prediction_match?.fault_origin ? "green" : "red")}
              ${tag(prediction.target || "not run", item.prediction_match?.target ? "green" : "red")}
            </div>
            <div class="small-note">Replacement: ${escapeHtml(String(prediction.replacement_recommended ?? "-"))}</div>
          </section>
        </div>
        <div class="experiment-message-grid">
          <section>
            <h3>证据日志</h3>
            ${renderExperimentMessageList(evidenceMessages)}
          </section>
          <section>
            <h3>原始日志预览</h3>
            ${renderExperimentMessageList(rawMessages)}
          </section>
        </div>
      </article>
    `;
  }).join("");
}

function renderExperimentMessageList(messages) {
  if (!messages.length) return `<div class="empty">No messages.</div>`;
  return `<ul class="signal-list">${messages.slice(0, 6).map((message) => `<li>${escapeHtml(message)}</li>`).join("")}</ul>`;
}

function formatMetric(value) {
  if (value === null || value === undefined) return "-";
  return `${Math.round(Number(value) * 1000) / 10}%`;
}

function formatDistribution(values) {
  const entries = Object.entries(values || {});
  if (!entries.length) return "-";
  return entries.map(([key, value]) => `${key}:${value}`).join(" / ");
}

function experimentLabel(value) {
  const labels = {
    non_fru_fault: "弱异常",
    no_fault_observed: "无故障观察",
  };
  return labels[value] || value || "-";
}

function renderAll() {
  if (!state.data) return;
  renderHeader();
  renderSummary();
  renderPlatformFacts();
  renderCoverage();
  renderBaseline();
  renderEvidenceLayers();
  renderMetrics();
  renderCategoryFilter();
  renderFrus();
  renderDiagnosis();
  renderEvents();
  renderActiveTests();
  renderCollectionSettings();
}

function updateRemoteModeUi() {
  const form = document.getElementById("remoteDiagnosisForm");
  const panel = document.getElementById("targetAgentPanel");
  if (!form || !panel) return;
  const mode = form.querySelector('input[name="remote_mode"]:checked')?.value || "interface";
  panel.hidden = mode !== "interface";
}

function renderTargetAgentStatus(result) {
  const container = document.getElementById("targetAgentStatus");
  if (!container) return;
  if (!result || result.ok === false) {
    container.className = "remote-agent-status error";
    container.innerHTML = `<strong>连接失败</strong><span>${escapeHtml(result?.error || "无法连接 Target Agent。")}</span>`;
    return;
  }
  const capabilities = result.capabilities || {};
  const health = result.health || {};
  const evidence = capabilities.evidence || {};
  const evidenceItems = Object.entries(evidence)
    .map(([key, value]) => `<span class="${value ? "ok" : "off"}">${escapeHtml(key)}: ${value ? "可采集" : "不可采集"}</span>`)
    .join("");
  if (result.collected) {
    const pkg = result.evidence_package || {};
    container.className = "remote-agent-status success";
    container.innerHTML = `
      <strong>采集完成</strong>
      <span>目标：${escapeHtml(result.target_url || "-")} · 设备：${escapeHtml(pkg.device_id || "-")} · 症状：${escapeHtml((pkg.symptom || []).join(", ") || "-")}</span>
      ${(pkg.warnings || []).length ? `<small>警告：${escapeHtml((pkg.warnings || []).slice(0, 3).join("；"))}</small>` : ""}
    `;
    return;
  }
  container.className = "remote-agent-status success";
  container.innerHTML = `
    <strong>${escapeHtml(health.service || "Target Agent")} 已连接</strong>
    <span>${escapeHtml(capabilities.hostname || health.hostname || "-")} · ${escapeHtml(capabilities.os_family || "-")} · ${escapeHtml(capabilities.agent_version || health.version || "-")}</span>
    <div class="agent-capability-list">${evidenceItems}</div>
  `;
}

function renderRemoteCollectionModule(plan = null) {
  const container = document.getElementById("remoteCollectionModule");
  if (!container) return;
  const activePlan = plan || buildRemoteCollectionPlanFromForm();
  const groups = activePlan.groups || [];
  const summary = activePlan.summary || "采集对方故障机器的诊断证据。";
  const required = activePlan.required_before_decision || [];
  container.innerHTML = `
    <div class="remote-collection-summary">
      <div>
        <span>${activePlan.can_export_runtime ? "可传输证据包" : "无法交互/断电"}</span>
        <strong>${escapeHtml(summary)}</strong>
      </div>
      <div class="remote-required-chips">
        ${required.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
      </div>
    </div>
    <div class="remote-collection-grid">
      ${groups.map(renderRemoteCollectionGroup).join("")}
    </div>
  `;
}

function buildRemoteCollectionPlanFromForm() {
  const form = document.getElementById("remoteDiagnosisForm");
  const mode = form?.querySelector('input[name="remote_mode"]:checked')?.value || "interface";
  const osFamily = form?.querySelector('select[name="os_family"]')?.value || "unknown";
  const symptoms = Array.from(form?.querySelectorAll('input[name="symptoms"]:checked') || []).map((item) => item.value);
  const canExport = mode === "interface" || mode === "offline";
  const modeGroups = mode === "offline" ? "offline" : canExport ? "interface" : "power_off";
  const groups = [remoteCollectionCatalog.base]
    .concat(remoteCollectionCatalog[modeGroups])
    .concat(canExport && remoteCollectionCatalog.os[osFamily] ? [remoteCollectionCatalog.os[osFamily]] : [])
    .concat(symptoms.map((symptom) => remoteCollectionCatalog.symptoms[symptom]).filter(Boolean));
  const uniqueGroups = [];
  const seen = new Set();
  groups.forEach((group) => {
    if (!group || seen.has(group.id)) return;
    seen.add(group.id);
    uniqueGroups.push(group);
  });
  const priorityOrder = { high: 0, medium: 1, low: 2 };
  uniqueGroups.sort((left, right) => (priorityOrder[left.priority] ?? 1) - (priorityOrder[right.priority] ?? 1));
  return {
    can_export_runtime: canExport,
    summary: mode === "offline"
      ? "导入从故障机系统盘、WinPE、安全模式或拆盘复制的 runtime_info、dump 和 evtx 摘要。"
      : canExport
      ? "先导出 runtime_info.json，再补充故障窗口日志和主动测试结果。"
      : "原机无法运行采集程序时，先记录现场可观察证据和外部隔离检查。",
    required_before_decision: canExport
      ? ["设备身份", "症状", "故障时间", "runtime_info.json"]
      : ["设备身份", "症状", "故障时间", "现场观察"],
    groups: uniqueGroups,
  };
}

function renderRemoteCollectionGroup(group) {
  const title = group.title || group.name || group.id;
  const priority = priorityLabel(group.priority);
  const tone = group.priority === "high" ? "red" : group.priority === "medium" ? "amber" : "gray";
  return `
    <article class="remote-collection-card">
      <div class="remote-collection-card-header">
        <div>
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(group.layer || "evidence")}</span>
        </div>
        ${tag(priority, tone)}
      </div>
      ${group.why ? `<p>${escapeHtml(group.why)}</p>` : ""}
      <ul>
        ${(group.items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </article>
  `;
}

function normalizeRemoteCollectionPlan(plan) {
  return {
    ...plan,
    groups: (plan.groups || []).map((group) => ({
      ...group,
      ...localizeRemoteCollectionGroup(group),
    })),
  };
}

function localizeRemoteCollectionGroup(group) {
  const localGroups = [
    remoteCollectionCatalog.base,
    ...remoteCollectionCatalog.interface,
    ...remoteCollectionCatalog.power_off,
    ...Object.values(remoteCollectionCatalog.os),
    ...Object.values(remoteCollectionCatalog.symptoms),
  ];
  const local = localGroups.find((item) => item.id === group.id);
  if (!local) {
    return { title: group.title || group.name || group.id };
  }
  return {
    title: local.title,
    items: local.items,
    layer: local.layer || group.layer,
    priority: local.priority || group.priority,
    why: "",
  };
}

function renderRemoteDiagnosisResult(result) {
  const container = document.getElementById("remoteDiagnosisResult");
  if (!container) return;
  const classification = result.classification || {};
  const boundary = result.boundary_assessment || classification.boundary_assessment || {};
  const decision = result.decision || {};
  const intake = result.intake || {};
  const nextTests = result.next_tests || [];
  const candidates = result.top_candidates || [];
  const guidance = result.guidance || result.remote_collection || {};
  if (guidance.collection_plan) {
    renderRemoteCollectionModule(normalizeRemoteCollectionPlan(guidance.collection_plan));
  }
  const scenario = result.scenario || {};
  const isPowerOff = guidance.scenario === "cross_machine_power_off" || scenario.id === "cross_machine_power_off";
  const isOffline = guidance.scenario === "cross_machine_offline" || scenario.id === "cross_machine_offline";
  const resultTitle = isPowerOff ? "现场/远程指导" : isOffline ? "离线证据诊断" : "诊断预览";
  const resultHint = isPowerOff
    ? "故障机无法传输数据，当前结论只用于指导观察、排查和后续取证，不扫描 dump。"
    : isOffline
    ? "已根据导入的离线证据运行诊断，建议补齐 dump、evtx、驱动列表和 SMART 信息。"
    : "已根据描述和可传输证据包生成预览，建议继续导出完整证据提高可信度。";
  container.innerHTML = `
    <div class="result-hero">
      <div>
        <span>${escapeHtml(resultTitle)}</span>
        <strong>${escapeHtml(faultClassLabel(classification.predicted_fault_class))}</strong>
        <small>${escapeHtml(resultHint)}</small>
      </div>
      <div>
        <span>决策结果</span>
        <strong>${escapeHtml(decisionLabel(decision.decision))}</strong>
        <small>${escapeHtml(decisionActionsNote(decision))}</small>
      </div>
    </div>
    <div class="compact-facts">
      <div><span>症状</span><strong>${escapeHtml((intake.symptoms || []).join(", "))}</strong></div>
      <div><span>设备</span><strong>${escapeHtml(`${intake.manufacturer || "-"} ${intake.model || ""}`.trim())}</strong></div>
      <div><span>系统</span><strong>${escapeHtml(intake.os_family || "-")}</strong></div>
    </div>
    <div class="remote-section">
      <h3>故障图推理</h3>
      <div id="remoteDiagnosisGraphPanel" class="diagnosis-graph-panel"></div>
    </div>
    <div class="remote-section boundary-section">
      <h3>软硬件边界判断</h3>
      ${renderBoundaryCard(boundary)}
    </div>
    <div class="remote-section next-actions">
      <h3>下一步</h3>
      <ul class="limitation-list">
        ${(guidance.base_actions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </div>
    <div class="remote-section" ${isPowerOff ? "hidden" : ""}>
      <h3>补采建议</h3>
      <div class="known-models">
        ${nextTests.length ? nextTests.map((test) => `
          <div class="known-model">
            <strong>${escapeHtml(test.name || test.id)}</strong>
            <span>${escapeHtml(test.id)} · score ${escapeHtml(test.score || 0)}</span>
          </div>
        `).join("") : `<div class="empty">当前证据不足，先导出对方机器 runtime_info.json。</div>`}
      </div>
    </div>
    ${isPowerOff ? `
      <div class="remote-section">
        <h3>不可交互处理原则</h3>
        <ul class="limitation-list">
          <li>不要把蓝屏或死机单独当作模块结论，先记录症状、发生时间、最近变更和可见硬件状态。</li>
          <li>优先排除外部电源、显示输出、外设、近期驱动或系统更新，再考虑硬件服务性对象。</li>
          <li>恢复可启动后再补采事件日志、dump、SMART、设备管理器和主动测试结果。</li>
        </ul>
      </div>
    ` : ""}
    <div class="remote-section">
      <h3>候选根因</h3>
      <div class="known-models">
        ${candidates.length ? candidates.slice(0, 3).map((candidate) => `
          <div class="known-model">
            <strong>${escapeHtml(candidate.fru_name || candidate.fru_id)}</strong>
            <span>${candidateTypeLabel(candidate)} · ${diagnosisStatusLabel(candidate.status)} · ${escapeHtml(candidate.rank_score ?? 0)}</span>
          </div>
        `).join("") : `<div class="empty">暂无候选根因。</div>`}
      </div>
    </div>
  `;
  renderDiagnosticGraphPanel({
    panelId: "remoteDiagnosisGraphPanel",
    detailId: "remoteDiagnosisGraphDetail",
    diagnosis: result,
    emptyMessage: "当前互机诊断没有返回故障图数据。请导入 runtime_info 或通过 Target Agent 采集证据。",
  });
}

function renderBoundaryCard(boundary = {}) {
  return `
    <div class="boundary-card">
      <div>
        <span>边界类型</span>
        <strong>${escapeHtml(boundaryTypeLabel(boundary.boundary_type))}</strong>
        <small>confidence ${escapeHtml(boundary.confidence ?? "-")}</small>
      </div>
      <p>${escapeHtml(boundary.reason || "等待边界证据。")}</p>
      <small>下一步：${escapeHtml(boundaryTestLabel(boundary.next_best_boundary_test))}</small>
    </div>
  `;
}

function renderQuickDiagnosisResult(result) {
  const container = document.getElementById("quickActionResult");
  if (!container) return;
  const health = result.health_assessment || {};
  const anomaly = result.anomaly_detection || {};
  const classification = result.classification || {};
  const boundary = result.boundary_assessment || classification.boundary_assessment || {};
  const decision = result.decision || {};
  const nextTests = result.next_tests || [];
  container.hidden = false;
  container.innerHTML = `
    <div class="quick-result-grid">
      <div>
        <span>健康度</span>
        <strong>${escapeHtml(health.health_score ?? "-")} / 100</strong>
        <small>${escapeHtml(healthLevelLabel(health.health_level))}</small>
      </div>
      <div>
        <span>异常检测</span>
        <strong>${escapeHtml(anomaly.status || "-")}</strong>
        <small>score ${escapeHtml(anomaly.anomaly_score ?? 0)}</small>
      </div>
      <div>
        <span>故障分类</span>
        <strong>${escapeHtml(faultClassLabel(classification.predicted_fault_class))}</strong>
        <small>${escapeHtml(classificationRankingNote(classification))}</small>
      </div>
      <div>
        <span>软硬件边界</span>
        <strong>${escapeHtml(boundaryTypeLabel(boundary.boundary_type))}</strong>
        <small>${escapeHtml(boundaryTestLabel(boundary.next_best_boundary_test))}</small>
      </div>
      <div>
        <span>决策</span>
        <strong>${escapeHtml(decisionLabel(decision.decision))}</strong>
        <small>${escapeHtml(decisionActionsNote(decision))}</small>
      </div>
    </div>
    ${nextTests.length ? `
      <div class="quick-next-tests">
        ${nextTests.slice(0, 3).map((test) => tag(test.name || test.id, "gray")).join("")}
      </div>
    ` : ""}
  `;
}

function renderHeader() {
  const summary = state.data.summary || {};
  const platform = state.data.platform || {};
  const selfBadge = document.getElementById("selfPlatformBadge");
  if (selfBadge) {
    selfBadge.textContent = `${platform.device_type || "-"} / ${platform.os_family || "-"}`;
  }
}

function renderSummary() {
  const summary = state.data.summary || {};
  const platform = state.data.platform || {};
  const coverage = summary.signal_coverage || {};
  const diagnosis = state.data.diagnosis?.summary || {};
  const boundary = state.data.boundary_assessment || diagnosis.boundary_assessment || diagnosis.classification?.boundary_assessment || {};
  const health = state.data.health_assessment || {};
  const systemHealth = state.data.system_health || {};
  const maintenance = health.maintenance_strategy || {};
  const cards = [
    ["健康度", `${health.health_score ?? systemHealth.health_score ?? "-"} / 100`, `${healthLevelLabel(health.health_level || systemHealth.level)} · ${maintenanceCadenceLabel(maintenance.cadence)}`],
    ["故障分类", faultClassLabel(diagnosis.fault_class || diagnosis.classification?.predicted_fault_class), classificationRankingNote(diagnosis.classification)],
    ["软硬件边界", boundaryTypeLabel(boundary.boundary_type), `${Math.round((boundary.confidence || 0) * 100)}% · ${boundaryTestLabel(boundary.next_best_boundary_test)}`],
    ["决策结果", decisionLabel(diagnosis.decision?.decision), decisionActionsNote(diagnosis.decision)],
    ["证据覆盖", `${coverage.average_score || 0}%`, `必要信号 ${coverage.required_present || 0}/${coverage.required_total || 0}`],
    ["异常上下文", summary.total_warning_error_count || 0, `问题设备 ${summary.problem_device_count || 0}`],
    ["设备", `${platform.manufacturer || "-"} ${platform.model || ""}`.trim(), platform.os_caption || platform.os_family || "待识别"],
  ];

  const html = cards.map(([title, value, note]) => metricCard(title, value, note)).join("");
  setHtml("selfSummaryGrid", html);
}

function renderPlatformFacts() {
  const platform = state.data.platform || {};
  const profile = state.data.profile || {};
  const summary = state.data.summary || {};
  const facts = [
    ["统一设备类型", platform.device_type],
    ["操作系统族", platform.os_family],
    ["采集器画像", platform.collector_profile],
    ["厂家", platform.manufacturer],
    ["型号", platform.model],
    ["诊断画像", profile.display_name],
    ["配置版本", summary.profile_version],
    ["运行数据窗口", `${summary.window_hours || "-"} 小时`],
    ["数据文件", summary.source_files?.runtime],
    ["历史快照目录", state.data.collection_resolved?.history_relative],
  ];

  const html = facts
    .map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value || "-")}</strong></div>`)
    .join("");
  setHtml("selfPlatformFacts", html);
}

function renderCollectionSettings() {
  const settings = state.settings || state.data?.collection_settings || {};
  const storage = settings.storage || {};
  const background = settings.background || {};
  const form = document.getElementById("collectionSettingsForm");
  if (form && Object.keys(settings).length) {
    form.elements.active_runtime_path.value = storage.active_runtime_path || "data/runtime_info.json";
    form.elements.history_dir.value = storage.history_dir || "data/history";
    form.elements.filename_template.value = storage.filename_template || "runtime_{timestamp}.json";
    form.elements.retention_count.value = storage.retention_count ?? 30;
    form.elements.interval_minutes.value = background.interval_minutes ?? 30;
    form.elements.hours.value = background.hours ?? 6;
    form.elements.max_system_events.value = background.max_system_events ?? 200;
    form.elements.max_application_events.value = background.max_application_events ?? 50;
    form.elements.save_history.checked = Boolean(storage.save_history);
    form.elements.background_enabled.checked = Boolean(background.enabled);
    form.elements.collect_runtime.checked = background.collect_runtime !== false;
    form.elements.scan_fru.checked = Boolean(background.scan_fru);
  }

  renderBackgroundStatus();
  renderHistorySnapshots();
}

function renderBackgroundStatus() {
  const status = state.backgroundStatus || state.data?.background_status || {};
  const settings = state.settings || state.data?.collection_settings || {};
  const resolved = state.resolved || state.data?.collection_resolved || {};
  const rows = [
    ["后台状态", status.running ? "运行中" : "未运行"],
    ["配置开关", settings.background?.enabled ? "已启用" : "未启用"],
    ["当前任务", status.current_task || "-"],
    ["最近状态", status.last_status || "-"],
    ["最近启动", status.last_started_at || "-"],
    ["最近完成", status.last_completed_at || "-"],
    ["下次运行", status.next_run_at || "-"],
    ["活动数据文件", resolved.active_runtime_relative || settings.storage?.active_runtime_path || "-"],
    ["历史目录", resolved.history_relative || settings.storage?.history_dir || "-"],
  ];
  const panel = document.getElementById("backgroundStatusPanel");
  if (!panel) return;
  panel.innerHTML = rows
    .map(([key, value]) => `<div class="kv"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
}

function renderHistorySnapshots() {
  const snapshots = state.history || state.data?.collection_history || [];
  const container = document.getElementById("historySnapshots");
  if (!container) return;
  if (!snapshots.length) {
    container.innerHTML = `<div class="empty">暂无历史快照。手动采集或后台采集成功后会自动生成。</div>`;
    return;
  }
  container.innerHTML = snapshots
    .map((snapshot) => `
      <div class="known-model">
        <strong>${escapeHtml(snapshot.filename || snapshot.path)}</strong>
        <span>${escapeHtml(snapshot.path || "-")}</span>
        <span>${escapeHtml(snapshot.modified_at || "-")} · ${formatBytes(snapshot.size_bytes || 0)}</span>
      </div>
    `)
    .join("");
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function renderCoverage() {
  const coverage = state.data.summary?.signal_coverage || {};
  const items = [
    ["必要信号", coverage.required_present || 0, coverage.required_total || 0],
    ["增强信号", coverage.enhancing_present || 0, coverage.enhancing_total || 0],
    ["主动测试", coverage.active_test_present || 0, coverage.active_test_total || 0],
  ];

  const html = items
    .map(([name, present, total]) => {
      const width = total ? Math.round((present / total) * 100) : 0;
      return `
        <div class="coverage-item">
          <div class="coverage-line"><span>${escapeHtml(name)}</span><strong>${present}/${total}</strong></div>
          <div class="bar-track"><i class="bar-fill" style="width:${width}%"></i></div>
        </div>
      `;
    })
    .join("");
  setHtml("selfCoveragePanel", html);
}

function renderBaseline() {
  renderBaselineSummary();
  renderBaselineBlocked();
  renderBaselineLayers();
  renderBaselinePlan();
}

function renderBaselineSummary() {
  const summary = state.data.collection_readiness || state.data.summary?.collection_readiness || {};
  const cards = [
    ["平均覆盖", `${summary.average_score || 0}%`, "保底证据包综合覆盖"],
    ["完全就绪", summary.ready_count || 0, "required 和 active test 均有结果"],
    ["被动就绪", summary.passive_ready_count || 0, "required 已齐，主动测试待补"],
    ["部分覆盖", summary.partial_count || 0, "已有部分证据但不够定位"],
    ["缺失对象", summary.missing_count || 0, "需要先补基础采集"],
  ];
  const container = document.getElementById("baselineSummary");
  if (!container) return;
  container.innerHTML = cards.map(([title, value, note]) => metricCard(title, value, note)).join("");
}

function renderBaselineBlocked() {
  const summary = state.data.collection_readiness || {};
  const container = document.getElementById("baselineBlocked");
  if (!container) return;
  const items = summary.lowest_score_frus || [];
  if (!items.length) {
    container.innerHTML = `<div class="empty">暂无诊断对象覆盖评分数据。</div>`;
    return;
  }
  container.innerHTML = items
    .map((item) => `
      <div class="known-model">
        <strong>${escapeHtml(item.fru_name || item.fru_id)}</strong>
        <span>${escapeHtml(item.fru_id)} · ${readinessTag(item.readiness)} · ${escapeHtml(item.score ?? 0)}%</span>
      </div>
    `)
    .join("");
}

function renderBaselineLayers() {
  const runtimeBaseline = state.data.runtime?.collection_baseline || {};
  const scope = runtimeBaseline.fru_scope || {};
  const container = document.getElementById("baselineLayers");
  if (!container) return;
  const rows = [
    ["采集策略", runtimeBaseline.strategy || "fault evidence baseline"],
    ["采集层", (runtimeBaseline.layers || ["inventory", "metrics", "logs", "active_tests"]).join(", ")],
    ["运行字段", (runtimeBaseline.required_runtime_sections || []).join(", ") || "-"],
  ];
  const scopeRows = Object.entries(scope)
    .map(([key, values]) => [key, Array.isArray(values) ? values.join(", ") : String(values)]);
  container.innerHTML = rows.concat(scopeRows)
    .map(([key, value]) => `
      <div class="kv">
        <span>${escapeHtml(key)}</span>
        <strong>${escapeHtml(value || "-")}</strong>
      </div>
    `)
    .join("");
}

function renderBaselinePlan() {
  const container = document.getElementById("baselinePlan");
  if (!container) return;
  const plans = state.data.collection_plan || [];
  if (!plans.length) {
    container.innerHTML = `<div class="empty">暂无保底采集计划。请确认已加载诊断画像和信号目录。</div>`;
    return;
  }
  container.innerHTML = plans.map(renderBaselineCard).join("");
}

function renderBaselineCard(plan) {
  const missingRequired = plan.missing_required || [];
  const missingActive = plan.missing_active_test || [];
  const missingEnhancing = plan.missing_enhancing || [];
  const actions = plan.next_actions || [];
  return `
    <article class="baseline-card ${escapeAttr(plan.readiness || "missing")}">
      <div class="fru-card-header">
        <div>
          <strong>${escapeHtml(plan.fru_name || plan.fru_id)}</strong>
          <span class="fru-id">${escapeHtml(plan.fru_id)} · ${escapeHtml(plan.category || "-")}</span>
        </div>
        <div class="score-pill">${escapeHtml(plan.score ?? 0)}%</div>
      </div>
      <div class="chip-row">
        ${tag(readinessLabel(plan.readiness), readinessTone(plan.readiness))}
        ${tag(`required 缺 ${missingRequired.length}`, missingRequired.length ? "amber" : "green")}
        ${tag(`active 缺 ${missingActive.length}`, missingActive.length ? "amber" : "green")}
        ${tag(`enhancing 缺 ${missingEnhancing.length}`, missingEnhancing.length ? "gray" : "green")}
      </div>
      ${plan.catalog_match === "fallback" ? `<p class="small-note">使用 ${escapeHtml(plan.catalog_fru_id)} 的通用采集模板。</p>` : ""}
      ${actions.length ? `
        <h3 class="subhead">下一轮优先采集</h3>
        <ul class="signal-list">
          ${actions.map((action) => `
            <li>
              <div class="signal-title">
                <strong>${escapeHtml(action.priority)}</strong>
                ${tag(action.source || "-", action.priority === "required" ? "amber" : "gray")}
              </div>
              <span class="small-label">${escapeHtml(action.key || "-")}</span>
              <div>${escapeHtml(action.description || "-")}</div>
            </li>
          `).join("")}
        </ul>
      ` : `<p class="small-note">当前最低证据包已覆盖，后续可进入评分或定位阶段。</p>`}
    </article>
  `;
}

function renderEvidenceLayers() {
  const layers = state.data.evidence_layers || [];
  const container = document.getElementById("evidenceLayers");
  if (!layers.length) {
    container.innerHTML = `<div class="empty">暂无证据层数据。</div>`;
    return;
  }

  container.innerHTML = layers
    .map((layer) => `
      <article class="evidence-card">
        <div class="fru-card-header">
          <div>
            <strong>${escapeHtml(layer.name)}</strong>
            <span class="fru-id">${escapeHtml(layer.id)}</span>
          </div>
          ${tag(statusLabel(layer.status), statusTone(layer.status))}
        </div>
        <p>${escapeHtml(layer.description)}</p>
        <div class="evidence-count">${escapeHtml(layer.records)} 条</div>
      </article>
    `)
    .join("");
}

function renderMetrics() {
  const container = document.getElementById("metricSections");
  const metrics = state.data.metrics || {};
  const sections = [
    ["system", "系统画像", metrics.system],
    ["bios", "固件", metrics.bios],
    ["mainboard", "主板", metrics.mainboard],
    ["power", "电源与电池", { ...(metrics.battery || {}), ...(prefixObject(metrics.power || {}, "power_")) }],
    ["storage", "存储", metrics.storage],
    ["memory", "内存", metrics.memory],
    ["network", "网络", metrics.network],
    ["display", "显示", metrics.display],
    ["input", "输入", metrics.input],
    ["camera", "摄像头", metrics.camera],
    ["audio", "音频", metrics.audio],
    ["usb_thermal", "USB 与热状态", { usb: metrics.usb, thermal: metrics.thermal, performance: metrics.performance }],
    ["inventory", "问题设备", metrics.device_inventory],
  ];

  container.innerHTML = sections
    .map(([id, title, data]) => `
      <section class="metric-block">
        <div class="metric-block-header">
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(id)}</span>
        </div>
        ${renderObjectTable(data)}
      </section>
    `)
    .join("");
}

function renderCategoryFilter() {
  const select = document.getElementById("categoryFilter");
  const categories = Array.from(
    new Set((state.data.target_frus || []).map((fru) => fru.category || "Unknown"))
  ).sort();
  const current = select.value;
  select.innerHTML = `<option value="">全部类别</option>${categories
    .map((category) => `<option value="${escapeAttr(category)}">${escapeHtml(category)}</option>`)
    .join("")}`;
  select.value = categories.includes(current) ? current : "";
}

function renderFrus() {
  const list = document.getElementById("fruList");
  const search = document.getElementById("fruSearch").value.trim().toLowerCase();
  const category = document.getElementById("categoryFilter").value;
  const frus = (state.data?.target_frus || []).filter((fru) => {
    const text = [
      fru.id,
      fru.name,
      fru.category,
      fru.description,
      ...(fru.aliases || []),
      ...flattenSignals(fru.signals),
    ]
      .join(" ")
      .toLowerCase();
    return (!search || text.includes(search)) && (!category || fru.category === category);
  });

  if (!frus.length) {
    list.innerHTML = `<div class="empty">没有符合筛选条件的服务性对象。</div>`;
    return;
  }

  list.innerHTML = frus.map(renderFruCard).join("");
}

function renderFruCard(fru) {
  const coverage = fru.coverage || {};
  const zh = fru.zh_explanation || {};
  const serviceability = fru.serviceability || {};
  const required = `${coverage.required_present || 0}/${coverage.required_total || 0}`;
  const enhancing = `${coverage.enhancing_present || 0}/${coverage.enhancing_total || 0}`;
  const active = `${coverage.active_test_present || 0}/${coverage.active_test_total || 0}`;
  const aliases = (fru.aliases || []).slice(0, 5).map((alias) => tag(alias, "gray")).join("");
  const limitations = (fru.replacement_limitations || [])
    .slice(0, 3)
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const commonSymptoms = (zh.common_symptoms || [])
    .slice(0, 4)
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const observableEvidence = (zh.observable_evidence || [])
    .slice(0, 4)
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const plan = fru.collection_plan || {};
  const nextActions = (plan.next_actions || [])
    .slice(0, 3)
    .map((action) => `<li>${escapeHtml(action.priority)} · ${escapeHtml(action.key)} · ${escapeHtml(action.description)}</li>`)
    .join("");

  return `
    <article class="fru-card">
      <div class="fru-card-header">
        <div>
          <strong>${escapeHtml(zh.name_zh || fru.name)}</strong>
          <span class="fru-id">${escapeHtml(fru.id)}</span>
        </div>
        ${tag(fru.verification_status || "unknown", tagTone(fru.verification_status))}
      </div>
      <p class="fru-description">${escapeHtml(zh.brief || fru.description || "-")}</p>
      <div class="chip-row">
        ${tag(zh.category_zh || fru.category || "Unknown", "gray")}
        ${tag(`必要 ${required}`, coverage.required_present === coverage.required_total ? "green" : "amber")}
        ${tag(`增强 ${enhancing}`, "gray")}
        ${tag(`主动 ${active}`, coverage.active_test_present ? "green" : "gray")}
        ${tag(`覆盖 ${coverage.score ?? 0}%`, readinessTone(coverage.readiness))}
        ${tag(serviceabilityTypeLabel(serviceability.type), serviceabilityTone(serviceability.type))}
        ${tag(serviceabilityLevelLabel(serviceability.level), "gray")}
      </div>
      ${aliases ? `<div class="chip-row alias-row">${aliases}</div>` : ""}
      ${zh.role ? `<div class="explanation-block"><strong>模块作用</strong><p>${escapeHtml(zh.role)}</p></div>` : ""}
      ${commonSymptoms ? `<div class="explanation-grid"><div><strong>常见故障表现</strong><ul class="plain-list">${commonSymptoms}</ul></div><div><strong>可观测证据</strong><ul class="plain-list">${observableEvidence}</ul></div></div>` : ""}
      ${zh.diagnosis_boundary ? `<div class="explanation-block warning"><strong>诊断边界</strong><p>${escapeHtml(zh.diagnosis_boundary)}</p></div>` : ""}
      ${serviceability.action ? `<div class="explanation-block"><strong>处置动作</strong><p>${escapeHtml(serviceability.action)}</p></div>` : ""}
      <ul class="signal-list">
        ${renderSignalGroup("必要信号", fru.signals?.required || [])}
        ${renderSignalGroup("主动测试", fru.signals?.active_test || [])}
      </ul>
      ${nextActions ? `<h3 class="subhead">下一轮补采</h3><ul class="limitation-list">${nextActions}</ul>` : ""}
      ${zh.replacement_caveat ? `<div class="explanation-block"><strong>更换后仍异常时</strong><p>${escapeHtml(zh.replacement_caveat)}</p></div>` : ""}
      ${limitations ? `<h3 class="subhead">更换后仍可能无法修复</h3><ul class="limitation-list">${limitations}</ul>` : ""}
    </article>
  `;
}

function renderSignalGroup(label, signals) {
  if (!signals.length) return "";
  return signals
    .slice(0, 4)
    .map((signal) => `
      <li>
        <div class="signal-title">
          <strong>${escapeHtml(label)}</strong>
          ${tag(signal.present ? "已覆盖" : "缺失", signal.present ? "green" : "amber")}
        </div>
        <span class="small-label">${escapeHtml(signal.key || "-")}</span>
        <div>${escapeHtml(signal.description || "-")}</div>
      </li>
    `)
    .join("");
}

function renderDiagnosis() {
  renderDiagnosisSummary();
  renderDiagnosisGraph();
  renderDiagnosisCandidates();
}

function renderDiagnosisSummary() {
  const diagnosis = state.data.diagnosis || {};
  const summary = diagnosis.summary || {};
  const boundary = state.data.boundary_assessment || summary.boundary_assessment || summary.classification?.boundary_assessment || {};
  const selfBadge = document.getElementById("selfDiagnosisBadge");
  if (selfBadge) {
    selfBadge.textContent = diagnosisStatusLabel(summary.status);
  }

  const cards = [
    ["结论状态", diagnosisStatusLabel(summary.status), summary.headline || "-"],
    ["故障分类", faultClassLabel(summary.fault_class || summary.classification?.predicted_fault_class), classificationRankingNote(summary.classification)],
    ["软硬件边界", boundaryTypeLabel(boundary.boundary_type), `${Math.round((boundary.confidence || 0) * 100)}% · ${boundaryTestLabel(boundary.next_best_boundary_test)}`],
    ["决策结果", decisionLabel(summary.decision?.decision), decisionActionsNote(summary.decision)],
    ["首位候选", summary.top_fru_id || "-", `综合分 ${summary.top_score || 0} / 置信度 ${confidenceLabel(summary.top_confidence)}`],
    ["可行动候选", summary.actionable_count || 0, `候选总数 ${summary.candidate_count || 0}`],
    ["异常上下文", summary.event_count || 0, `问题设备 ${summary.problem_device_count || 0}`],
  ];
  const html = cards.map(([title, value, note]) => metricCard(title, value, note)).join("");
  setHtml("selfDiagnosisSummary", html);

  const items = diagnosis.non_fru_risks || [];
  const whyNotReplace = summary.why_not_replace || [];
  if (!items.length && !whyNotReplace.length) {
    setHtml("selfDiagnosisRisks", "");
    return;
  }
  const replacementRows = whyNotReplace
    .map((reason) => `
      <div class="risk-item">
        ${tag("暂不建议硬件更换", "amber")}
        <span>${escapeHtml(reason)}</span>
      </div>
    `)
    .join("");
  const riskRows = items
    .map((item) => `
      <div class="risk-item">
        ${tag(item.category || "风险", "amber")}
        <span>${escapeHtml(item.risk || "-")}</span>
      </div>
    `)
    .join("");
  const riskHtml = replacementRows + riskRows;
  setHtml("selfDiagnosisRisks", riskHtml);
}

function renderDiagnosisGraph() {
  const diagnosis = state.data?.diagnosis || {};
  renderDiagnosticGraphPanel({
    panelId: "diagnosisGraphPanel",
    badgeId: "diagnosisGraphBadge",
    detailId: "diagnosisGraphDetail",
    diagnosis,
    emptyMessage: "暂无故障图数据。请先运行诊断或刷新仪表盘。",
  });
}

function renderDiagnosticGraphPanel({
  panelId,
  badgeId = "",
  detailId,
  diagnosis = {},
  emptyMessage = "暂无故障图数据。",
}) {
  const panel = document.getElementById(panelId);
  const badge = badgeId ? document.getElementById(badgeId) : null;
  if (!panel) return;
  const graph = diagnosis.diagnostic_graph || {};
  const inference = diagnosis.graph_inference || {};
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];
  if (!nodes.length) {
    panel.innerHTML = `<div class="empty">${escapeHtml(emptyMessage)}</div>`;
    if (badge) badge.textContent = "-";
    return;
  }

  const view = buildDiagnosisGraphView(graph, inference);
  const summary = graph.metadata || {};
  const topCandidate = (inference.candidate_ranking || [])[0];
  const topFault = (inference.fault_ranking || [])[0];
  if (badge) {
    badge.textContent = `${summary.node_count || nodes.length} nodes / ${summary.edge_count || edges.length} edges`;
  }

  panel.innerHTML = `
    <div class="diagnosis-graph-summary">
      ${metricCard("图节点", summary.node_count || nodes.length, graphSummaryText(summary.node_type_counts))}
      ${metricCard("图边", summary.edge_count || edges.length, graphSummaryText(summary.edge_type_counts))}
      ${metricCard("Top Candidate", topCandidate?.label || topCandidate?.id || "-", graphScoreNote(topCandidate))}
      ${metricCard("Top Fault", faultClassLabel(topFault?.id), graphScoreNote(topFault))}
    </div>
    <div class="diagnosis-graph-layout">
      <div class="diagnosis-graph-canvas" aria-label="diagnostic graph visualization">
        ${renderDiagnosisGraphSvg(view)}
      </div>
      <aside class="diagnosis-graph-detail" id="${escapeAttr(detailId)}">
        ${renderDiagnosisGraphDefaultDetail(inference)}
      </aside>
    </div>
    <div class="diagnosis-graph-legend">
      ${renderGraphLegendItem("证据", "evidence")}
      ${renderGraphLegendItem("组件", "component")}
      ${renderGraphLegendItem("候选根因", "candidate")}
      ${renderGraphLegendItem("故障类别", "fault")}
      <span class="graph-edge-sample support"></span><span>支持</span>
      <span class="graph-edge-sample conflict"></span><span>反证</span>
      <span class="graph-edge-sample structural"></span><span>结构关系</span>
    </div>
  `;
  bindDiagnosisGraphInteractions(panel, view, graph, inference, detailId);
}

function buildDiagnosisGraphView(graph, inference) {
  const ranking = new Map();
  (inference.candidate_ranking || []).forEach((item) => ranking.set(item.node_id, item));
  (inference.fault_ranking || []).forEach((item) => ranking.set(item.node_id, item));
  const rawNodes = graph.nodes || [];
  const rawEdges = graph.edges || [];
  const nodeById = new Map(rawNodes.map((node) => [node.id, node]));
  const selected = new Set();
  (inference.candidate_ranking || []).slice(0, 8).forEach((item) => selected.add(item.node_id));
  (inference.fault_ranking || [])
    .filter((item) => (item.posterior || 0) > 0 || (item.support || 0) > 0)
    .slice(0, 6)
    .forEach((item) => selected.add(item.node_id));

  const priorityEdges = rawEdges
    .map((edge, index) => ({ ...edge, viewIndex: index }))
    .sort((left, right) => edgePriority(right) - edgePriority(left));
  priorityEdges.forEach((edge) => {
    if (selected.size >= 44) return;
    if (selected.has(edge.target) || selected.has(edge.source) || isEvidenceEdge(edge)) {
      selected.add(edge.source);
      selected.add(edge.target);
    }
  });

  rawNodes
    .slice()
    .sort((left, right) => nodePriority(right, ranking) - nodePriority(left, ranking))
    .forEach((node) => {
      if (selected.size < 34) selected.add(node.id);
    });

  const nodes = rawNodes
    .filter((node) => selected.has(node.id))
    .map((node) => ({ ...node, ranking: ranking.get(node.id) || null }));
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edges = priorityEdges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .slice(0, 90);
  return layoutDiagnosisGraph(nodes, edges);
}

function layoutDiagnosisGraph(nodes, edges) {
  const columns = [
    { id: "evidence", x: 54, width: 190, title: "Evidence" },
    { id: "component", x: 286, width: 150, title: "Component" },
    { id: "candidate", x: 488, width: 190, title: "Candidate" },
    { id: "fault", x: 734, width: 150, title: "Fault" },
  ];
  const byColumn = Object.fromEntries(columns.map((column) => [column.id, []]));
  nodes.forEach((node) => byColumn[graphColumnForNode(node)].push(node));
  columns.forEach((column) => {
    byColumn[column.id].sort((left, right) => nodePriority(right, new Map()) - nodePriority(left, new Map()));
  });
  const maxRows = Math.max(...columns.map((column) => byColumn[column.id].length), 1);
  const height = Math.max(380, 74 + maxRows * 62);
  const positions = {};
  columns.forEach((column) => {
    const list = byColumn[column.id];
    const gap = Math.max(52, (height - 96) / Math.max(list.length, 1));
    list.forEach((node, index) => {
      positions[node.id] = {
        x: column.x,
        y: 56 + index * gap,
        width: column.width,
        height: 42,
        column: column.id,
      };
    });
  });
  return { nodes, edges, positions, columns, width: 930, height };
}

function renderDiagnosisGraphSvg(view) {
  const edgeHtml = view.edges.map((edge) => renderGraphEdge(edge, view.positions)).join("");
  const nodeHtml = view.nodes.map((node) => renderGraphNode(node, view.positions[node.id])).join("");
  const headers = view.columns.map((column) => `
    <text x="${column.x}" y="24" class="graph-column-label">${escapeHtml(column.title)}</text>
  `).join("");
  return `
    <svg class="diagnosis-graph-svg" viewBox="0 0 ${view.width} ${view.height}" role="img">
      <defs>
        <marker id="graphArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
          <path d="M 0 0 L 8 4 L 0 8 z"></path>
        </marker>
      </defs>
      ${headers}
      <g class="graph-edges">${edgeHtml}</g>
      <g class="graph-nodes">${nodeHtml}</g>
    </svg>
  `;
}

function renderGraphEdge(edge, positions) {
  const source = positions[edge.source];
  const target = positions[edge.target];
  if (!source || !target) return "";
  const x1 = source.x + source.width;
  const y1 = source.y + source.height / 2;
  const x2 = target.x;
  const y2 = target.y + target.height / 2;
  const mid = Math.max(24, Math.abs(x2 - x1) * 0.42);
  const path = `M ${x1} ${y1} C ${x1 + mid} ${y1}, ${x2 - mid} ${y2}, ${x2} ${y2}`;
  const edgeClass = graphEdgeClass(edge.type);
  return `
    <path class="graph-edge ${edgeClass}" d="${path}" data-edge-index="${escapeAttr(edge.viewIndex)}"></path>
  `;
}

function renderGraphNode(node, position) {
  if (!position) return "";
  const nodeClass = graphColumnForNode(node);
  const ranking = node.ranking || {};
  const score = ranking.posterior !== undefined ? Math.round((ranking.posterior || 0) * 100) : Math.round((node.prior || 0) * 100);
  const label = compactGraphLabel(node.label || node.id, 22);
  const subtitle = node.type === "fault_class" ? faultClassLabel(node.metadata?.fault_class || node.id.split(":").pop()) : graphNodeTypeLabel(node.type);
  return `
    <g class="graph-node ${nodeClass}" data-node-id="${escapeAttr(node.id)}" transform="translate(${position.x} ${position.y})" tabindex="0" role="button">
      <rect width="${position.width}" height="${position.height}" rx="6"></rect>
      <text x="10" y="17" class="graph-node-title">${escapeHtml(label)}</text>
      <text x="10" y="32" class="graph-node-subtitle">${escapeHtml(subtitle)}</text>
      <text x="${position.width - 10}" y="25" class="graph-node-score">${escapeHtml(score)}</text>
    </g>
  `;
}

function bindDiagnosisGraphInteractions(panel, view, graph, inference, detailId) {
  panel.querySelectorAll(".graph-node[data-node-id]").forEach((nodeElement) => {
    const handler = () => showDiagnosisGraphNodeDetail(nodeElement.dataset.nodeId, graph, inference, detailId);
    nodeElement.addEventListener("click", handler);
    nodeElement.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handler();
      }
    });
  });
  panel.querySelectorAll(".graph-edge[data-edge-index]").forEach((edgeElement) => {
    edgeElement.addEventListener("click", () => showDiagnosisGraphEdgeDetail(Number(edgeElement.dataset.edgeIndex), graph, detailId));
  });
  if (view.nodes.length) {
    showDiagnosisGraphNodeDetail(view.nodes[0].id, graph, inference, detailId);
  }
}

function showDiagnosisGraphNodeDetail(nodeId, graph, inference, detailId) {
  const detail = document.getElementById(detailId);
  const node = (graph.nodes || []).find((item) => item.id === nodeId);
  if (!detail || !node) return;
  const ranking = findGraphRanking(nodeId, inference);
  const connected = (graph.edges || [])
    .map((edge, index) => ({ ...edge, viewIndex: index }))
    .filter((edge) => edge.source === nodeId || edge.target === nodeId)
    .sort((left, right) => edgePriority(right) - edgePriority(left))
    .slice(0, 8);
  detail.innerHTML = `
    <div class="graph-detail-heading">
      ${tag(graphNodeTypeLabel(node.type), graphNodeTone(node.type))}
      <h3>${escapeHtml(node.label || node.id)}</h3>
      <span class="small-label">${escapeHtml(node.id)}</span>
    </div>
    <div class="compact-facts graph-detail-facts">
      <div><span>Posterior</span><strong>${escapeHtml(formatGraphScore(ranking?.posterior))}</strong></div>
      <div><span>Support</span><strong>${escapeHtml(ranking?.support ?? "-")}</strong></div>
      <div><span>Conflict</span><strong>${escapeHtml(ranking?.conflict ?? "-")}</strong></div>
    </div>
    <h3 class="subhead">关联边</h3>
    <ul class="signal-list graph-edge-list">
      ${connected.length ? connected.map((edge) => renderGraphDetailEdge(edge)).join("") : `<li class="muted-list-item">暂无关联边</li>`}
    </ul>
    ${renderGraphNodeMetadata(node.metadata)}
  `;
}

function showDiagnosisGraphEdgeDetail(edgeIndex, graph, detailId) {
  const detail = document.getElementById(detailId);
  const edge = (graph.edges || [])[edgeIndex];
  if (!detail || !edge) return;
  const nodeById = new Map((graph.nodes || []).map((node) => [node.id, node]));
  detail.innerHTML = `
    <div class="graph-detail-heading">
      ${tag(graphEdgeLabel(edge.type), graphEdgeTone(edge.type))}
      <h3>${escapeHtml(graphEdgeLabel(edge.type))}</h3>
      <span class="small-label">weight ${escapeHtml(edge.weight ?? "-")}</span>
    </div>
    <div class="graph-edge-detail-row">
      <strong>${escapeHtml(nodeById.get(edge.source)?.label || edge.source)}</strong>
      <span>→</span>
      <strong>${escapeHtml(nodeById.get(edge.target)?.label || edge.target)}</strong>
    </div>
    ${edge.metadata?.reason ? `<div class="explanation-block"><strong>Reason</strong><p>${escapeHtml(edge.metadata.reason)}</p></div>` : ""}
    ${renderGraphNodeMetadata(edge.metadata)}
  `;
}

function renderDiagnosisGraphDefaultDetail(inference) {
  const candidates = inference.candidate_ranking || [];
  const faults = inference.fault_ranking || [];
  return `
    <div class="graph-detail-heading">
      ${tag("graph inference", "blue")}
      <h3>推理摘要</h3>
      <span class="small-label">${escapeHtml(inference.method?.name || "-")}</span>
    </div>
    <h3 class="subhead">候选根因</h3>
    <ul class="signal-list graph-edge-list">
      ${candidates.slice(0, 4).map((item) => `
        <li><strong>${escapeHtml(item.label || item.id)}</strong><span class="small-label">posterior ${formatGraphScore(item.posterior)} / support ${escapeHtml(item.support ?? "-")}</span></li>
      `).join("") || `<li class="muted-list-item">暂无候选</li>`}
    </ul>
    <h3 class="subhead">故障类别</h3>
    <ul class="signal-list graph-edge-list">
      ${faults.slice(0, 4).map((item) => `
        <li><strong>${escapeHtml(faultClassLabel(item.id))}</strong><span class="small-label">posterior ${formatGraphScore(item.posterior)} / support ${escapeHtml(item.support ?? "-")}</span></li>
      `).join("") || `<li class="muted-list-item">暂无类别</li>`}
    </ul>
  `;
}

function renderGraphDetailEdge(edge) {
  return `
    <li>
      <div class="signal-title">
        <strong>${escapeHtml(graphEdgeLabel(edge.type))}</strong>
        ${tag(`w ${edge.weight ?? "-"}`, graphEdgeTone(edge.type))}
      </div>
      <span class="small-label">${escapeHtml(edge.source)} → ${escapeHtml(edge.target)}</span>
      ${edge.metadata?.reason ? `<div>${escapeHtml(edge.metadata.reason)}</div>` : ""}
    </li>
  `;
}

function renderGraphNodeMetadata(metadata = {}) {
  const keys = Object.keys(metadata || {}).filter((key) => !["sample"].includes(key));
  if (!keys.length) return "";
  return `
    <details class="graph-metadata">
      <summary>metadata</summary>
      <pre>${escapeHtml(JSON.stringify(metadata, null, 2))}</pre>
    </details>
  `;
}

function renderGraphLegendItem(label, tone) {
  return `<span class="graph-node-sample ${escapeAttr(tone)}"></span><span>${escapeHtml(label)}</span>`;
}

function graphColumnForNode(node) {
  if (node.type === "candidate") return "candidate";
  if (node.type === "fault_class") return "fault";
  if (node.type === "component") return "component";
  return "evidence";
}

function graphNodeTypeLabel(type) {
  const labels = {
    case: "case",
    log_template: "log",
    metric_signal: "metric",
    active_test: "active test",
    crash_signature: "crash",
    inventory_signal: "inventory",
    weak_signal: "weak signal",
    component: "component",
    candidate: "candidate",
    fault_class: "fault class",
  };
  return labels[type] || type || "-";
}

function graphNodeTone(type) {
  if (type === "candidate") return "amber";
  if (type === "fault_class") return "red";
  if (type === "component") return "gray";
  return "blue";
}

function graphEdgeClass(type) {
  if (String(type).startsWith("contradicts")) return "conflict";
  if (String(type).startsWith("supports") || type === "maps_to_fault") return "support";
  return "structural";
}

function graphEdgeTone(type) {
  if (String(type).startsWith("contradicts")) return "red";
  if (String(type).startsWith("supports") || type === "maps_to_fault") return "green";
  return "gray";
}

function graphEdgeLabel(type) {
  const labels = {
    supports_candidate: "supports candidate",
    supports_fault: "supports fault",
    contradicts_candidate: "contradicts candidate",
    contradicts_fault: "contradicts fault",
    maps_to_fault: "maps to fault",
    contains: "contains",
    emitted_by: "emitted by",
  };
  return labels[type] || type || "-";
}

function isEvidenceEdge(edge) {
  return ["supports_candidate", "supports_fault", "contradicts_candidate", "contradicts_fault"].includes(edge.type);
}

function edgePriority(edge) {
  const base = isEvidenceEdge(edge) ? 100 : edge.type === "maps_to_fault" ? 65 : 20;
  return base + Number(edge.weight || 0) * 10;
}

function nodePriority(node, ranking = new Map()) {
  const rank = ranking.get(node.id) || node.ranking || {};
  const rankScore = Number(rank.posterior || 0) * 100 + Number(rank.support || 0) * 8 - Number(rank.conflict || 0) * 5;
  const typeScore = node.type === "candidate" ? 80 : node.type === "fault_class" ? 70 : node.type === "active_test" ? 60 : node.type === "crash_signature" ? 58 : node.type === "log_template" ? 42 : 25;
  return rankScore + typeScore + Number(node.prior || 0) * 20;
}

function findGraphRanking(nodeId, inference) {
  return (inference.candidate_ranking || []).concat(inference.fault_ranking || []).find((item) => item.node_id === nodeId);
}

function formatGraphScore(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${Math.round(Number(value) * 100)}%`;
}

function graphScoreNote(item) {
  if (!item) return "-";
  return `posterior ${formatGraphScore(item.posterior)} / support ${item.support ?? "-"}`;
}

function graphSummaryText(counts = {}) {
  const entries = Object.entries(counts || {});
  if (!entries.length) return "-";
  return entries.slice(0, 3).map(([key, value]) => `${key}:${value}`).join(" / ");
}

function compactGraphLabel(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function renderDiagnosisCandidates() {
  const candidates = state.data.diagnosis?.top_candidates || [];
  if (!candidates.length) {
    const empty = `<div class="empty">暂无诊断候选。请先加载诊断画像并采集运行数据。</div>`;
    setHtml("selfDiagnosisCandidates", empty);
    return;
  }
  const html = candidates.map(renderDiagnosisCandidate).join("");
  setHtml("selfDiagnosisCandidates", html);
}

function renderDiagnosisCandidate(candidate) {
  const matches = candidate.matched_evidence || [];
  const negatives = candidate.negative_evidence || [];
  const missing = candidate.missing_evidence || [];
  const actions = candidate.next_actions || [];
  return `
    <article class="diagnosis-card ${escapeAttr(candidate.status || "needs_data")}">
      <div class="fru-card-header">
        <div>
          <strong>${escapeHtml(candidate.fru_name || candidate.fru_id)}</strong>
          <span class="fru-id">${escapeHtml(candidate.fru_id)} · ${escapeHtml(candidate.category || "-")} · ${candidateTypeLabel(candidate)}</span>
        </div>
        <div class="score-pill">${escapeHtml(candidate.rank_score ?? 0)}</div>
      </div>
      <div class="chip-row">
        ${tag(candidateTypeLabel(candidate), candidate.candidate_type === "non_fru_fault" ? "amber" : "gray")}
        ${tag(boundaryRoleLabel(candidate.boundary_role), "gray")}
        ${tag(diagnosisStatusLabel(candidate.status), diagnosisTone(candidate.status))}
        ${tag(`置信度 ${confidenceLabel(candidate.confidence)}`, confidenceTone(candidate.confidence))}
        ${tag(`异常 ${candidate.matched_rule_count || 0}`, matches.length ? "amber" : "gray")}
        ${tag(`反证 ${candidate.negative_rule_count || 0}`, negatives.length ? "green" : "gray")}
        ${tag(`采集 ${candidate.collection_score ?? 0}%`, readinessTone(candidate.readiness))}
      </div>
      <p class="fru-description">${escapeHtml(candidate.explanation || "-")}</p>
      ${candidate.boundary_reason ? `<div class="explanation-block"><strong>边界角色</strong><p>${escapeHtml(candidate.boundary_reason)}</p></div>` : ""}
      ${candidate.repair_action ? `<div class="explanation-block warning"><strong>处理建议</strong><p>${escapeHtml(candidate.repair_action)}</p></div>` : ""}
      <div class="diagnosis-evidence-grid">
        ${renderEvidenceColumn("命中证据", matches, "amber")}
        ${renderEvidenceColumn("反证/正常", negatives, "green")}
        ${renderEvidenceColumn("缺失证据", missing, "gray")}
      </div>
      ${actions.length ? `
        <h3 class="subhead">下一步排查</h3>
        <ul class="limitation-list">
          ${actions.map((action) => `
            <li>
              <strong>${escapeHtml(action.priority || "-")}</strong>
              <span class="small-label">${escapeHtml(action.key || action.source || "-")}</span>
              <div>${escapeHtml(action.description || "-")}</div>
            </li>
          `).join("")}
        </ul>
      ` : ""}
    </article>
  `;
}

function renderEvidenceColumn(title, items, tone) {
  const body = items.length
    ? items.slice(0, 3).map((item) => `
        <li>
          <div class="signal-title">
            <strong>${escapeHtml(item.rule_id || item.type || "-")}</strong>
            ${tag(item.type || "-", tone)}
          </div>
          <span class="small-label">${escapeHtml(item.source || "-")} · weight ${escapeHtml(item.weight ?? "-")}</span>
          <div>${escapeHtml(item.description || "-")}</div>
          ${(item.details || []).length ? `<small>${escapeHtml((item.details || []).join("；"))}</small>` : ""}
        </li>
      `).join("")
    : `<li class="muted-list-item">暂无</li>`;
  return `
    <section>
      <h3>${escapeHtml(title)}</h3>
      <ul class="signal-list">${body}</ul>
    </section>
  `;
}

function renderEvents() {
  const buckets = state.data.summary?.event_buckets || [];
  const container = document.getElementById("eventBuckets");
  renderEventWindow();
  if (!buckets.length) {
    container.innerHTML = `<div class="empty">暂无事件聚合数据。</div>`;
    return;
  }

  container.innerHTML = buckets
    .map((bucket) => `
      <article class="event-card">
        <div class="fru-card-header">
          <h3>${escapeHtml(bucket.name)}</h3>
          ${tag(`Total ${bucket.total_count}`, bucket.total_count > 0 ? "amber" : "green")}
        </div>
        <div class="event-counts">
          ${tag(`Error ${bucket.error_count}`, bucket.error_count > 0 ? "red" : "gray")}
          ${tag(`Warning ${bucket.warning_count}`, bucket.warning_count > 0 ? "amber" : "gray")}
        </div>
        <div class="event-rules">
          <span>Provider: ${escapeHtml((bucket.rules?.provider_patterns || []).join(", ") || "-")}</span>
          <span>Message: ${escapeHtml((bucket.rules?.message_patterns || []).join(", ") || "-")}</span>
        </div>
        <div class="sample-list">
          ${(bucket.samples || []).slice(0, 4).map(renderEventSample).join("") || "<p>无样例事件。</p>"}
        </div>
      </article>
    `)
    .join("");
}

function renderEventWindow() {
  const box = document.getElementById("eventWindow");
  const collection = state.data.summary?.event_collection || {};
  if (!Object.keys(collection).length) {
    box.innerHTML = `<div class="empty">尚未记录日志采集窗口。可输入故障发生时间后重新采集。</div>`;
    return;
  }

  const modeLabel = collection.mode === "fault_window" ? "故障时间窗" : "最近时间窗";
  box.innerHTML = `
    <div class="kv-grid compact-kv">
      <div class="kv"><span>采集模式</span><strong>${escapeHtml(modeLabel)}</strong></div>
      <div class="kv"><span>开始时间</span><strong>${escapeHtml(collection.start_time || "-")}</strong></div>
      <div class="kv"><span>结束时间</span><strong>${escapeHtml(collection.end_time || "-")}</strong></div>
      <div class="kv"><span>故障时间</span><strong>${escapeHtml(collection.fault_time || "-")}</strong></div>
      <div class="kv"><span>System 日志</span><strong>${escapeHtml(collection.system_event_count ?? 0)}</strong></div>
      <div class="kv"><span>Application 日志</span><strong>${escapeHtml(collection.application_event_count ?? 0)}</strong></div>
    </div>
  `;
}

function renderEventSample(sample) {
  const normalized = normalizeSample(sample);
  return `
    <div class="sample-row">
      <span>${escapeHtml(normalized.time_created || "-")}</span>
      <strong>${escapeHtml(normalized.provider || "-")}</strong>
      <span>${escapeHtml(String(normalized.event_id ?? "-"))}</span>
      <small>${escapeHtml(normalized.log_name || "-")} · ${escapeHtml(normalized.level || "-")}</small>
      <em>${escapeHtml((normalized.matched_provider_patterns || []).concat(normalized.matched_message_patterns || []).join(", ") || "-")}</em>
      <p>${escapeHtml(normalized.message_excerpt || "")}</p>
    </div>
  `;
}

function renderActiveTests() {
  const selfContainer = document.getElementById("selfActiveTests");
  const tests = state.data.metrics?.tests || {};
  const groups = Object.entries(tests);
  if (!groups.length) {
    const empty = `<div class="empty">暂无主动测试字段。</div>`;
    if (selfContainer) selfContainer.innerHTML = empty;
    return;
  }

  const html = groups
    .map(([group, values]) => `
      <article class="test-card">
        <h3>${escapeHtml(group)}</h3>
        ${Object.entries(values || {}).map(([key, value]) => renderTestRow(group, key, value)).join("")}
      </article>
    `)
    .join("");
  if (selfContainer) selfContainer.innerHTML = html;

  selfContainer?.querySelectorAll("select[data-test-key]").forEach((select) => {
    select.addEventListener("change", () => updateActiveTest(select.dataset.testKey, select.value));
  });
}

function renderTestRow(group, key, value) {
  const fullKey = `tests.${group}.${key}`;
  const options = ["not_run", "passed", "failed", "inconclusive", "not_applicable"];
  return `
    <div class="test-row">
      <div>
        <strong>${escapeHtml(key)}</strong>
        <span class="small-label">${escapeHtml(fullKey)}</span>
      </div>
      <select class="select" data-test-key="${escapeAttr(fullKey)}">
        ${options.map((option) => `<option value="${option}" ${option === value ? "selected" : ""}>${testLabel(option)}</option>`).join("")}
      </select>
    </div>
  `;
}

function renderObjectTable(data) {
  if (!data || (typeof data === "object" && !Object.keys(data).length)) {
    return `<div class="empty">暂无数据。</div>`;
  }
  const rows = Object.entries(data).map(([key, value]) => `
    <tr>
      <th>${escapeHtml(key)}</th>
      <td>${formatValue(value)}</td>
    </tr>
  `);
  return `<table class="metric-table"><tbody>${rows.join("")}</tbody></table>`;
}

function metricCard(title, value, note) {
  return `
    <div class="metric-card">
      <span>${escapeHtml(title)}</span>
      <strong>${escapeHtml(value ?? "-")}</strong>
      <small>${escapeHtml(note || "")}</small>
    </div>
  `;
}

function renderBarList(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) return `<div class="empty">暂无分类数据。</div>`;
  const max = Math.max(...entries.map(([, count]) => count), 1);
  return entries
    .map(([name, count]) => {
      const width = Math.round((count / max) * 100);
      return `
        <div class="bar-row">
          <span title="${escapeAttr(name)}">${escapeHtml(name)}</span>
          <div class="bar-track"><i class="bar-fill" style="width:${width}%"></i></div>
          <strong>${escapeHtml(count)}</strong>
        </div>
      `;
    })
    .join("");
}

function tag(text, tone = "gray") {
  return `<span class="tag ${escapeAttr(tone)}">${escapeHtml(text ?? "-")}</span>`;
}

function tagTone(value) {
  if (value === "official_service_manual" || value === "official_spec") return "green";
  if (value === "detected_only" || value === "model_inferred") return "amber";
  return "gray";
}

function statusTone(status) {
  if (status === "ready" || status === "done") return "green";
  if (status === "partial" || status === "planned") return "amber";
  return "red";
}

function statusLabel(status) {
  const labels = {
    ready: "可用",
    done: "已完成",
    partial: "部分完成",
    planned: "待接入",
    missing: "缺失",
  };
  return labels[status] || status || "-";
}

function readinessLabel(readiness) {
  const labels = {
    ready: "完全就绪",
    passive_ready: "被动就绪",
    partial: "部分覆盖",
    missing: "缺失",
  };
  return labels[readiness] || readiness || "-";
}

function readinessTone(readiness) {
  if (readiness === "ready" || readiness === "passive_ready") return "green";
  if (readiness === "partial") return "amber";
  return "red";
}

function readinessTag(readiness) {
  return readinessLabel(readiness);
}

function healthLevelLabel(level) {
  const labels = {
    healthy: "健康",
    minor: "轻微异常",
    diagnose: "需要进一步诊断",
    urgent: "需要立即处理",
  };
  return labels[level] || level || "-";
}

function maintenanceCadenceLabel(cadence) {
  const labels = {
    normal_baseline_monitoring: "常规监测",
    observe_next_24_to_72_hours: "观察 24-72 小时",
    run_targeted_diagnostics_before_repair: "先做定向诊断",
    handle_before_continued_use: "继续使用前处理",
  };
  return labels[cadence] || cadence || "-";
}

function diagnosisStatusLabel(status) {
  const labels = {
    suspect_found: "发现重点嫌疑",
    possible_found: "存在弱嫌疑",
    non_fru_found: "软件/环境根因",
    non_fru_possible: "软件/环境风险",
    insufficient_evidence: "证据不足",
    missing_profile: "缺少画像",
    suspect: "重点嫌疑",
    possible: "弱嫌疑",
    unlikely: "当前不支持",
    needs_data: "待补采",
    no_evidence: "无异常证据",
  };
  return labels[status] || status || "-";
}

function diagnosisTone(status) {
  if (status === "suspect" || status === "suspect_found") return "red";
  if (status === "non_fru_found") return "amber";
  if (status === "possible" || status === "possible_found" || status === "non_fru_possible" || status === "needs_data") return "amber";
  if (status === "unlikely" || status === "no_evidence") return "green";
  return "gray";
}

function candidateTypeLabel(candidate) {
  if (candidate?.candidate_type === "non_fru_fault") return "软件/配置/环境根因";
  if (candidate?.candidate_type === "serviceable_assembly") return "硬件总成候选";
  if (candidate?.candidate_type === "non_replaceable_subsystem") return "板载子系统证据";
  if (candidate?.candidate_type === "external_part") return "外部件/附件";
  if (candidate?.diagnosis_role === "subsystem") return "子系统证据";
  return "硬件更换候选";
}

function priorityLabel(priority) {
  const labels = {
    high: "高优先级",
    medium: "中优先级",
    low: "低优先级",
  };
  return labels[priority] || priority || "优先级";
}

function faultOriginLabel(origin) {
  const labels = {
    replaceable_fru: "硬件更换候选",
    serviceable_assembly: "硬件总成候选",
    non_replaceable_subsystem: "板载子系统证据",
    external_part: "外部件/附件",
    maintenance_condition: "维护状态",
    non_fru_fault: "软件/配置/环境根因",
    mixed_or_uncertain: "混合/不确定",
    subsystem: "子系统",
    unknown: "未知",
  };
  return labels[origin] || origin || "-";
}

function faultClassLabel(faultClass) {
  const labels = {
    driver_fault: "驱动故障",
    os_fault: "操作系统故障",
    firmware_fault: "固件故障",
    configuration_fault: "配置故障",
    external_environment_fault: "外部环境故障",
    hardware_fault: "硬件边界故障",
    data_or_filesystem_fault: "数据/文件系统故障",
    mixed_or_uncertain: "混合/不确定",
  };
  return labels[faultClass] || faultClass || "-";
}

function boundaryTypeLabel(type) {
  const labels = {
    software_side: "软件侧",
    hardware_side: "硬件侧",
    hardware_software_boundary: "软硬件边界",
    mixed_or_uncertain: "混合/不确定",
  };
  return labels[type] || type || "待判断";
}

function boundaryRoleLabel(role) {
  const labels = {
    software_side: "软件侧",
    firmware_control: "固件/控制",
    interface_path: "接口路径",
    hardware_endpoint: "硬件端点",
    external_environment: "外部环境",
  };
  return labels[role] || role || "边界角色未知";
}

function boundaryTestLabel(test) {
  const labels = {
    collect_minidump_and_correlate_with_whea_driver_storage_events: "采集 minidump 并关联 WHEA/驱动/存储事件",
    run_known_good_adapter_test_and_collect_acpi_ucsi_battery_state: "已知正常适配器测试 + ACPI/UCSI/电池状态",
    run_external_display_test_and_compare_driver_event_timeline: "外接屏测试 + 显示驱动事件对比",
    run_gateway_ping_driver_state_and_hotspot_comparison: "网关 ping + 驱动状态 + 热点对比",
    run_confirmatory_hardware_active_test: "执行确认性硬件主动测试",
    rollback_or_update_driver_then_retest_symptom: "回滚/更新驱动后复测症状",
    collect_fault_window_logs_and_run_low_risk_active_tests: "采集故障窗口日志并执行低风险主动测试",
  };
  return labels[test] || test || "待补充边界区分测试";
}

function classificationRankingNote(classification) {
  const ranking = classification?.class_ranking || [];
  if (!ranking.length) return "待补充分类证据";
  return ranking
    .slice(0, 2)
    .map((item) => `${faultClassLabel(item.fault_class)} ${Math.round((item.score || 0) * 100)}%`)
    .join(" / ");
}

function decisionLabel(decision) {
  const labels = {
    software_repairable: "软件修复",
    firmware_repairable: "固件处理",
    configuration_repairable: "配置修复",
    externally_reproducible: "环境复测",
    replaceable_hardware_or_service_required: "硬件确认后处置",
    need_more_evidence: "继续补采证据",
  };
  return labels[decision] || decision || "-";
}

function decisionActionsNote(decision) {
  const actions = decision?.actions || [];
  if (!actions.length) return "分类完成后再生成处置动作";
  return actions.slice(0, 2).join(" / ");
}

function serviceabilityTypeLabel(type) {
  const labels = {
    replaceable_fru: "硬件更换候选",
    serviceable_assembly: "硬件总成候选",
    non_replaceable_subsystem: "板载子系统",
    non_fru_fault: "软件/配置/环境",
    external_part: "外部件",
    maintenance_condition: "维护项",
  };
  return labels[type] || type || "服务性未知";
}

function serviceabilityLevelLabel(level) {
  const labels = {
    field_replaceable: "现场可换",
    service_center_replaceable: "服务站可换",
    assembly_replaceable: "总成更换",
    not_individually_replaceable: "不可单独更换",
    external: "外部替换",
    not_replaceable: "无需硬件更换",
  };
  return labels[level] || level || "-";
}

function serviceabilityTone(type) {
  if (type === "replaceable_fru" || type === "external_part") return "green";
  if (type === "serviceable_assembly") return "amber";
  if (type === "non_replaceable_subsystem" || type === "non_fru_fault") return "red";
  return "gray";
}

function replacementRecommendationLabel(value) {
  const labels = {
    recommended: "建议硬件更换",
    recommended_after_confirmation: "确认后可硬件更换",
    not_recommended: "不建议直接硬件更换",
    not_yet_recommended: "暂不建议硬件更换",
    collect_more_evidence: "先补充证据",
  };
  return labels[value] || value || "-";
}

function confidenceLabel(confidence) {
  const labels = {
    high: "高",
    medium: "中",
    low: "低",
    none: "无",
  };
  return labels[confidence] || confidence || "-";
}

function confidenceTone(confidence) {
  if (confidence === "high") return "green";
  if (confidence === "medium") return "amber";
  if (confidence === "low") return "gray";
  return "gray";
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
  }
  if (typeof value === "object") {
    return `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
  }
  return escapeHtml(String(value));
}

function flattenSignals(signals) {
  if (!signals) return [];
  return Object.values(signals)
    .flat()
    .map((signal) => `${signal.key || ""} ${signal.description || ""}`);
}

function prefixObject(object, prefix) {
  return Object.fromEntries(Object.entries(object).map(([key, value]) => [`${prefix}${key}`, value]));
}

function setHtml(id, html) {
  const element = document.getElementById(id);
  if (element) element.innerHTML = html;
}

function normalizeSample(sample) {
  if (typeof sample === "string") {
    return { provider: sample, event_id: "-", time_created: "-" };
  }
  return sample || {};
}

function setDefaultFaultTime() {
  const input = document.getElementById("faultTimeInput");
  if (!input || input.value) {
    return;
  }
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  input.value = now.toISOString().slice(0, 16);
}

function testLabel(value) {
  const labels = {
    not_run: "未测试",
    passed: "通过",
    failed: "失败",
    inconclusive: "不确定",
    not_applicable: "不适用",
  };
  return labels[value] || value;
}

function setBusy(isBusy) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.classList.contains("nav-item")) return;
    if (button.id === "refreshBtn") return;
    button.disabled = isBusy;
  });

  if (state.actionButton && !state.actionButton.classList.contains("nav-item")) {
    state.actionButton.classList.toggle("is-loading", isBusy);
    state.actionButton.setAttribute("aria-busy", String(isBusy));
    if (!isBusy) {
      state.actionButton.removeAttribute("aria-busy");
      state.actionButton = null;
    }
  }
}

function showStatus(message, tone = "") {
  const box = document.getElementById("statusBox");
  box.hidden = false;
  box.className = `status-box ${tone}`;
  box.textContent = message;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}
