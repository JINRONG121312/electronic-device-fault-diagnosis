param(
    [string]$OutputPath = "configs\detected_device.json",
    [switch]$NoProgress
)

$ErrorActionPreference = "Stop"
$scanTimer = [System.Diagnostics.Stopwatch]::StartNew()
$script:ProgressStep = 0
$script:ProgressTotal = 13
$script:ProgressActivity = "FRU hardware scan"

function Update-ScanProgress {
    param([string]$Status)

    if ($NoProgress) {
        return
    }

    $script:ProgressStep += 1
    $percent = [Math]::Min(100, [Math]::Round(($script:ProgressStep / $script:ProgressTotal) * 100))
    Write-Progress -Activity $script:ProgressActivity -Status $Status -PercentComplete $percent
}

function New-EvidenceRule {
    param(
        [string]$Id,
        [string]$EvidenceType,
        [string]$Source,
        [string]$Pattern,
        [double]$Weight,
        [string]$Description,
        [string]$Metric = $null,
        [string]$Operator = $null,
        [object]$Threshold = $null
    )

    $rule = [ordered]@{
        id = $Id
        evidence_type = $EvidenceType
        source = $Source
        weight = $Weight
        description = $Description
    }

    if ($Pattern) { $rule.pattern = $Pattern }
    if ($Metric) { $rule.metric = $Metric }
    if ($Operator) { $rule.operator = $Operator }
    if ($null -ne $Threshold) { $rule.threshold = $Threshold }

    return $rule
}

function New-FRU {
    param(
        [string]$Id,
        [string]$Name,
        [string]$Category,
        [string]$Description,
        [string[]]$Aliases,
        [object[]]$EvidenceRules
    )

    return [ordered]@{
        id = $Id
        name = $Name
        category = $Category
        replaceable = $true
        description = $Description
        aliases = $Aliases
        evidence_rules = $EvidenceRules
    }
}

function ConvertTo-SafeId {
    param([string]$Value)

    $id = $Value.ToLowerInvariant() -replace "[^a-z0-9]+", "_"
    $id = $id.Trim("_")
    if (-not $id) {
        return "unknown"
    }
    return $id
}

function Add-FRU {
    param([object]$Fru)

    if (-not $script:fruIds.Contains($Fru.id)) {
        [void]$script:fruIds.Add($Fru.id)
        [void]$script:fruList.Add($Fru)
    }
}

function Test-IsVirtualDeviceName {
    param([string]$Name)

    if (-not $Name) {
        return $false
    }

    return $Name -match "virtual|vpn|vmware|hyper-v|loopback|tap|sharing monitor|gameviewer|remote|radmin"
}

Update-ScanProgress "Reading system identity"
$computer = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$baseboard = Get-CimInstance Win32_BaseBoard
$os = Get-CimInstance Win32_OperatingSystem

$script:fruList = [System.Collections.ArrayList]::new()
$script:fruIds = [System.Collections.Generic.HashSet[string]]::new()

Update-ScanProgress "Reading device inventory"
$pnpDevices = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue)
$networkAdaptersAll = @(Get-CimInstance Win32_NetworkAdapter -ErrorAction SilentlyContinue)
$videoControllersAll = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue)

Update-ScanProgress "Reading battery modules"
$batteries = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue)
foreach ($battery in $batteries) {
    $safe = ConvertTo-SafeId "$($battery.DeviceID)_$($battery.Name)"
    Add-FRU (New-FRU `
        -Id "battery_$safe" `
        -Name "Battery Pack - $($battery.Name)" `
        -Category "PowerFRU" `
        -Description "Detected battery module. Status=$($battery.Status); EstimatedChargeRemaining=$($battery.EstimatedChargeRemaining)." `
        -Aliases @("battery", "bms", "power") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "battery_${safe}_charge_low" -EvidenceType "metric_threshold" -Source "battery_status" -Metric "estimated_charge_remaining" -Operator "<" -Threshold 10 -Weight 0.3 -Description "Battery charge is critically low."),
            (New-EvidenceRule -Id "battery_${safe}_power_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "battery|charging|acpi|kernel-power" -Weight 0.5 -Description "Power or charging events appear in system logs.")
        ))
}

Update-ScanProgress "Reading storage modules"
$physicalDisks = @(Get-CimInstance Win32_DiskDrive -ErrorAction SilentlyContinue)
foreach ($disk in $physicalDisks) {
    $safe = ConvertTo-SafeId "$($disk.Index)_$($disk.Model)"
    Add-FRU (New-FRU `
        -Id "storage_$safe" `
        -Name "Storage Drive - $($disk.Model)" `
        -Category "StorageFRU" `
        -Description "Detected storage module. Interface=$($disk.InterfaceType); SizeBytes=$($disk.Size); Status=$($disk.Status)." `
        -Aliases @("disk", "ssd", "hdd", "nvme", "storage") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "storage_${safe}_smart_warning" -EvidenceType "health_warning" -Source "smart" -Pattern "critical_warning|media_errors|predictive failure|bad block" -Weight 1.0 -Description "SMART or storage health data reports a warning."),
            (New-EvidenceRule -Id "storage_${safe}_io_error_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "disk|ntfs|storahci|stornvme|bad block|io error" -Weight 0.8 -Description "Storage-related errors appear in system logs.")
        ))
}

Update-ScanProgress "Reading memory modules"
$memoryModules = @(Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue)
$memoryIndex = 0
foreach ($memory in $memoryModules) {
    $memoryIndex += 1
    $locator = if ($memory.DeviceLocator) { $memory.DeviceLocator } else { "slot_$memoryIndex" }
    $safe = ConvertTo-SafeId $locator
    Add-FRU (New-FRU `
        -Id "memory_$safe" `
        -Name "Memory Module - $locator" `
        -Category "ComputeFRU" `
        -Description "Detected memory module. CapacityBytes=$($memory.Capacity); SpeedMHz=$($memory.Speed); Manufacturer=$($memory.Manufacturer)." `
        -Aliases @("memory", "ram", "dimm") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "memory_${safe}_bugcheck_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "memory management|page fault|bugcheck|whea" -Weight 0.8 -Description "Crash logs contain memory-related patterns."),
            (New-EvidenceRule -Id "memory_${safe}_active_test_failed" -EvidenceType "active_test" -Source "memory_test" -Pattern "failed" -Weight 1.0 -Description "Active memory test reports failures.")
        ))
}

Update-ScanProgress "Reading network modules"
$virtualNetworkAdapters = @()
$networkAdapters = @($networkAdaptersAll | Where-Object {
    $_.PhysicalAdapter -eq $true -and (
        $_.Name -match "Wi-Fi|Wireless|WLAN|Bluetooth|Ethernet|Intel|Realtek|Qualcomm|Broadcom|MediaTek"
    ) -and -not (Test-IsVirtualDeviceName $_.Name)
})
$virtualNetworkAdapters = @($networkAdaptersAll | Where-Object {
    Test-IsVirtualDeviceName $_.Name
})
foreach ($adapter in $networkAdapters) {
    $safe = ConvertTo-SafeId "$($adapter.DeviceID)_$($adapter.Name)"
    $isWireless = $adapter.Name -match "Wi-Fi|Wireless|WLAN|Bluetooth"
    $aliases = if ($isWireless) { @("wifi", "wlan", "bluetooth", "network") } else { @("ethernet", "nic", "network") }
    Add-FRU (New-FRU `
        -Id "network_$safe" `
        -Name "Network Adapter - $($adapter.Name)" `
        -Category "CommunicationFRU" `
        -Description "Detected communication module. NetConnectionStatus=$($adapter.NetConnectionStatus)." `
        -Aliases $aliases `
        -EvidenceRules @(
            (New-EvidenceRule -Id "network_${safe}_driver_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "wlan|wifi|netwtw|bluetooth|ethernet|adapter reset|link down|link up" -Weight 0.7 -Description "Network adapter reset, disconnect, or link-flap events appear in logs."),
            (New-EvidenceRule -Id "network_${safe}_device_missing" -EvidenceType "device_state" -Source "device_inventory" -Pattern "network_missing|adapter_disabled|device_problem" -Weight 1.0 -Description "Network adapter is missing, disabled, or reporting a device problem.")
        ))
}

Update-ScanProgress "Reading display modules"
$virtualVideoControllers = @()
$videoControllers = @($videoControllersAll | Where-Object {
    -not (Test-IsVirtualDeviceName $_.Name)
})
$virtualVideoControllers = @($videoControllersAll | Where-Object {
    Test-IsVirtualDeviceName $_.Name
})
foreach ($video in $videoControllers) {
    $safe = ConvertTo-SafeId "$($video.DeviceID)_$($video.Name)"
    Add-FRU (New-FRU `
        -Id "display_$safe" `
        -Name "Display Adapter - $($video.Name)" `
        -Category "DisplayFRU" `
        -Description "Detected display-related module. DriverVersion=$($video.DriverVersion); Status=$($video.Status)." `
        -Aliases @("display", "screen", "graphics", "gpu") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "display_${safe}_driver_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "display|graphics|nvlddmkm|amdkmdag|igfx|dxgkrnl" -Weight 0.6 -Description "Display or graphics driver errors appear in logs."),
            (New-EvidenceRule -Id "display_${safe}_active_test_failed" -EvidenceType "active_test" -Source "display_test" -Pattern "external_ok_internal_failed|display_failed" -Weight 1.0 -Description "Display active test reports a panel or output failure.")
        ))
}

$monitorDevices = @($pnpDevices | Where-Object {
    (
        $_.PNPClass -eq "Monitor" -or
        $_.Name -match "Monitor|Display|Panel"
    ) -and -not (Test-IsVirtualDeviceName $_.Name)
})
if ($monitorDevices.Count -gt 0) {
    Add-FRU (New-FRU `
        -Id "display_internal_panel" `
        -Name "Internal or PnP Display Panel" `
        -Category "DisplayFRU" `
        -Description "Detected display panel or monitor device. DeviceCount=$($monitorDevices.Count)." `
        -Aliases @("display", "screen", "panel", "monitor", "edp") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "display_panel_device_error" -EvidenceType "device_state" -Source "device_inventory" -Pattern "display_missing|monitor_problem|panel_problem" -Weight 0.8 -Description "Display panel or monitor device is missing or reporting a problem."),
            (New-EvidenceRule -Id "display_panel_active_test_failed" -EvidenceType "active_test" -Source "display_test" -Pattern "external_ok_internal_failed|display_failed" -Weight 1.0 -Description "Display active test reports panel failure.")
        ))
}

Update-ScanProgress "Reading input modules"
$keyboards = @(Get-CimInstance Win32_Keyboard -ErrorAction SilentlyContinue)
if ($keyboards.Count -gt 0) {
    Add-FRU (New-FRU `
        -Id "input_keyboard_touchpad" `
        -Name "Keyboard and Touchpad Assembly" `
        -Category "InputFRU" `
        -Description "Detected keyboard or HID input assembly. KeyboardCount=$($keyboards.Count)." `
        -Aliases @("keyboard", "touchpad", "hid", "input") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "input_hid_error_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "hid|keyboard|touchpad|i2c hid" -Weight 0.7 -Description "HID device errors appear in system logs."),
            (New-EvidenceRule -Id "input_active_test_failed" -EvidenceType "active_test" -Source "input_test" -Pattern "key_failed|touchpad_failed" -Weight 1.0 -Description "Input active test reports keyboard or touchpad failure.")
        ))
}

$touchpadDevices = @($pnpDevices | Where-Object {
    $_.Name -match "Touchpad|Trackpad|I2C HID" -and -not (Test-IsVirtualDeviceName $_.Name)
})
if ($touchpadDevices.Count -gt 0) {
    Add-FRU (New-FRU `
        -Id "input_touchpad" `
        -Name "Touchpad Module" `
        -Category "InputFRU" `
        -Description "Detected touchpad or I2C HID input module. DeviceCount=$($touchpadDevices.Count)." `
        -Aliases @("touchpad", "trackpad", "i2c hid", "input") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "touchpad_hid_error_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "touchpad|i2c hid|hid" -Weight 0.7 -Description "Touchpad or I2C HID errors appear in system logs."),
            (New-EvidenceRule -Id "touchpad_active_test_failed" -EvidenceType "active_test" -Source "input_test" -Pattern "touchpad_failed" -Weight 1.0 -Description "Touchpad active test reports touchpad failure.")
        ))
}

Update-ScanProgress "Reading camera and audio modules"
$cameraDevices = @($pnpDevices | Where-Object {
    $_.Name -match "Camera|Webcam|Integrated Camera|USB2\.0 HD UVC|UVC Camera" -and -not (Test-IsVirtualDeviceName $_.Name)
})
if ($cameraDevices.Count -gt 0) {
    Add-FRU (New-FRU `
        -Id "sensor_camera" `
        -Name "Camera Module" `
        -Category "SensorFRU" `
        -Description "Detected camera module. DeviceCount=$($cameraDevices.Count)." `
        -Aliases @("camera", "webcam", "uvc") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "camera_device_error" -EvidenceType "device_state" -Source "device_inventory" -Pattern "camera_missing|camera_device_problem" -Weight 0.9 -Description "Camera device is missing or reporting a device problem."),
            (New-EvidenceRule -Id "camera_active_test_failed" -EvidenceType "active_test" -Source "camera_test" -Pattern "camera_failed" -Weight 1.0 -Description "Camera active test reports camera failure.")
        ))
}

$audioDevices = @(Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "Audio|Realtek|Speaker|Sound" -and -not (Test-IsVirtualDeviceName $_.Name)
})
if ($audioDevices.Count -gt 0) {
    Add-FRU (New-FRU `
        -Id "interface_audio_speaker" `
        -Name "Audio and Speaker Subsystem" `
        -Category "InterfaceFRU" `
        -Description "Detected audio subsystem. DeviceCount=$($audioDevices.Count)." `
        -Aliases @("speaker", "audio", "sound") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "audio_device_error" -EvidenceType "device_state" -Source "device_inventory" -Pattern "audio_missing|audio_device_problem" -Weight 0.6 -Description "Audio device is missing or reporting a device problem."),
            (New-EvidenceRule -Id "speaker_active_test_failed" -EvidenceType "active_test" -Source "audio_test" -Pattern "speaker_failed|left_channel_failed|right_channel_failed" -Weight 1.0 -Description "Audio active test reports speaker output failure.")
        ))
}

Update-ScanProgress "Reading I/O modules"
$usbControllers = @(Get-CimInstance Win32_USBController -ErrorAction SilentlyContinue)
if ($usbControllers.Count -gt 0) {
    Add-FRU (New-FRU `
        -Id "interface_usb_controller" `
        -Name "USB Interface Controller" `
        -Category "InterfaceFRU" `
        -Description "Detected USB interface subsystem. ControllerCount=$($usbControllers.Count)." `
        -Aliases @("usb", "type-c", "interface", "io") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "usb_enum_failure_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "usb|device not recognized|hub|ucmucsi|type-c" -Weight 0.7 -Description "USB enumeration or Type-C errors appear in system logs."),
            (New-EvidenceRule -Id "usb_active_test_failed" -EvidenceType "active_test" -Source "usb_test" -Pattern "usb_port_failed" -Weight 1.0 -Description "USB active test reports port failure.")
        ))
}

Update-ScanProgress "Reading compute and thermal modules"
$processors = @(Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue)
foreach ($processor in $processors) {
    $safe = ConvertTo-SafeId "$($processor.DeviceID)_$($processor.Name)"
    Add-FRU (New-FRU `
        -Id "compute_$safe" `
        -Name "Compute Module - $($processor.Name)" `
        -Category "ComputeFRU" `
        -Description "Detected compute module. Cores=$($processor.NumberOfCores); LogicalProcessors=$($processor.NumberOfLogicalProcessors); Status=$($processor.Status)." `
        -Aliases @("cpu", "processor", "compute") `
        -EvidenceRules @(
            (New-EvidenceRule -Id "compute_${safe}_whea_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "whea|machine check|processor|thermal throttling" -Weight 0.8 -Description "Processor or WHEA hardware errors appear in logs.")
        ))
}

Add-FRU (New-FRU `
    -Id "thermal_cooling_subsystem" `
    -Name "Cooling and Thermal Subsystem" `
    -Category "ThermalFRU" `
    -Description "Logical thermal FRU. Windows often does not expose the physical fan as a separate WMI FRU." `
    -Aliases @("fan", "cooling", "thermal") `
    -EvidenceRules @(
        (New-EvidenceRule -Id "thermal_throttling_metric" -EvidenceType "metric_threshold" -Source "thermal_metrics" -Metric "thermal_throttle_ratio" -Operator ">" -Threshold 0.2 -Weight 0.9 -Description "CPU or GPU is frequently thermal throttled."),
        (New-EvidenceRule -Id "thermal_kernel_power_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "thermal|kernel-power|overheat|throttle" -Weight 0.7 -Description "Thermal or unexpected power events appear in system logs.")
    ))

$boardName = if ($baseboard.Product) { "$($baseboard.Manufacturer) $($baseboard.Product)" } else { "Mainboard" }
Add-FRU (New-FRU `
    -Id "mainboard" `
    -Name $boardName `
    -Category "MainboardFRU" `
    -Description "Detected main system board." `
    -Aliases @("mainboard", "motherboard", "system board") `
    -EvidenceRules @(
        (New-EvidenceRule -Id "mainboard_multi_bus_failure" -EvidenceType "device_state" -Source "device_inventory" -Pattern "multi_bus_failure|pci_problem|acpi_problem" -Weight 0.8 -Description "Multiple independent onboard buses or devices fail together."),
        (New-EvidenceRule -Id "mainboard_whea_log" -EvidenceType "log_pattern" -Source "system_event_log" -Pattern "whea|acpi|pci express|firmware" -Weight 0.6 -Description "Low-level platform or bus errors appear in system logs.")
    ))

$deviceType = "electronic_information_device"
$chassis = @(Get-CimInstance Win32_SystemEnclosure -ErrorAction SilentlyContinue)
if ($computer.PCSystemType -in @(2)) {
    $deviceType = "laptop"
} elseif ($computer.PCSystemType -in @(3, 4, 5)) {
    $deviceType = "desktop_or_server"
}

$profile = [ordered]@{
    device_type = $deviceType
    display_name = "$($computer.Manufacturer) $($computer.Model)"
    version = "1.0"
    description = "Auto-detected FRU profile generated from Windows CIM/WMI hardware inventory."
    metadata = [ordered]@{
        generator = "scripts/detect_fru.ps1"
        generated_at = (Get-Date).ToString("s")
        computer_name = $env:COMPUTERNAME
        manufacturer = $computer.Manufacturer
        model = $computer.Model
        os_caption = $os.Caption
        os_version = $os.Version
        pc_system_type = $computer.PCSystemType
        chassis_types = @($chassis | ForEach-Object { $_.ChassisTypes }) | Select-Object -First 16
        ignored_virtual_network_adapters = @($virtualNetworkAdapters | ForEach-Object { $_.Name })
        ignored_virtual_display_adapters = @($virtualVideoControllers | ForEach-Object { $_.Name })
    }
    fru_list = @($script:fruList)
}

Update-ScanProgress "Writing detected FRU profile"
$output = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath
} else {
    Join-Path (Resolve-Path -Path ".").Path $OutputPath
}
$outputDir = Split-Path -Parent $output
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$profile | ConvertTo-Json -Depth 12 | Set-Content -Path $output -Encoding UTF8
$scanTimer.Stop()
if (-not $NoProgress) {
    Write-Progress -Activity $script:ProgressActivity -Completed
}

Write-Output "Detected device: $($profile.display_name)"
Write-Output "Device type: $($profile.device_type)"
Write-Output "FRU count: $($script:fruList.Count)"
Write-Output "Output: $output"
Write-Output "Elapsed seconds: $([Math]::Round($scanTimer.Elapsed.TotalSeconds, 2))"
Write-Output ""
Write-Output "Detected FRUs:"
foreach ($fru in $script:fruList) {
    Write-Output "- $($fru.id): $($fru.name) [$($fru.category)]"
}
