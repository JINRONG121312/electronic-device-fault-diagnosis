param(
    [string]$OutputPath = "data\runtime_info.json",
    [int]$Hours = 24,
    [int]$MaxSystemEvents = 500,
    [int]$MaxApplicationEvents = 150,
    [string]$FaultTime = "",
    [int]$BeforeFaultMinutes = 60,
    [int]$AfterFaultMinutes = 15,
    [switch]$NoProgress
)

$ErrorActionPreference = "Stop"
$scanTimer = [System.Diagnostics.Stopwatch]::StartNew()
$script:ProgressStep = 0
$script:ProgressTotal = 11
$script:ProgressActivity = "Runtime information collection"
$script:CollectionStatus = [ordered]@{}

function Update-ScanProgress {
    param([string]$Status)

    if ($NoProgress) {
        return
    }

    $script:ProgressStep += 1
    $percent = [Math]::Min(100, [Math]::Round(($script:ProgressStep / $script:ProgressTotal) * 100))
    Write-Progress -Activity $script:ProgressActivity -Status $Status -PercentComplete $percent
}

function Set-CollectionStatus {
    param(
        [string]$SourceName,
        [string]$Status,
        [string]$ErrorMessage = $null
    )

    if (-not $SourceName) {
        return
    }

    $script:CollectionStatus[$SourceName] = [ordered]@{
        status = $Status
        error = $ErrorMessage
    }
}

function Try-Collect {
    param(
        [scriptblock]$Script,
        [object]$DefaultValue,
        [string]$SourceName = ""
    )

    try {
        $result = & $Script
        Set-CollectionStatus -SourceName $SourceName -Status "collected"
        return $result
    } catch {
        $message = if ($_.Exception -and $_.Exception.Message) { $_.Exception.Message } else { "collection failed" }
        Set-CollectionStatus -SourceName $SourceName -Status "failed" -ErrorMessage ($message -replace "\s+", " ")
        return $DefaultValue
    }
}

function ConvertTo-StatusObject {
    param([object]$Item)

    return [ordered]@{
        present = $true
        name = $Item.Name
        status = $Item.Status
        pnp_class = $Item.PNPClass
        problem_code = $Item.ConfigManagerErrorCode
    }
}

function ConvertTo-BoolOrNull {
    param([object]$Value)

    if ($null -eq $Value) {
        return $null
    }

    try {
        return [bool]$Value
    } catch {
        return $null
    }
}

function Test-IsVirtualDeviceName {
    param([string]$Name)

    if (-not $Name) {
        return $false
    }

    return $Name -match "virtual|vpn|vmware|hyper-v|loopback|tap|sharing monitor|gameviewer|remote|radmin"
}

function Test-IsVirtualNetworkAdapter {
    param([object]$Adapter)

    if ($null -eq $Adapter) {
        return $true
    }

    return (Test-IsVirtualDeviceName ([string]$Adapter.Name)) -or
        (Test-IsVirtualDeviceName ([string]$Adapter.InterfaceDescription))
}

function Limit-Text {
    param(
        [string]$Value,
        [int]$MaxLength = 500
    )

    if (-not $Value) {
        return ""
    }

    $text = $Value -replace "\s+", " "
    if ($text.Length -le $MaxLength) {
        return $text
    }

    return $text.Substring(0, $MaxLength) + "..."
}

function Get-EventBucket {
    param(
        [object[]]$Events,
        [string[]]$ProviderPatterns,
        [string[]]$MessagePatterns
    )

    $bucketEvents = [System.Collections.ArrayList]::new()
    foreach ($event in $Events) {
        $provider = [string]$event.provider
        $message = [string]$event.message

        $matchedProviderPatterns = @()
        foreach ($pattern in $ProviderPatterns) {
            if ($provider -match $pattern) {
                $matchedProviderPatterns += $pattern
            }
        }

        $matchedMessagePatterns = @()
        foreach ($pattern in $MessagePatterns) {
            if ($message -match $pattern) {
                $matchedMessagePatterns += $pattern
            }
        }

        if ($matchedProviderPatterns.Count -gt 0 -or $matchedMessagePatterns.Count -gt 0) {
            [void]$bucketEvents.Add([ordered]@{
                event = $event
                matched_provider_patterns = $matchedProviderPatterns
                matched_message_patterns = $matchedMessagePatterns
            })
        }
    }

    return [ordered]@{
        error_count = @($bucketEvents | Where-Object { $_.event.level_number -eq 2 -or $_.event.level -eq "Error" -or $_.event.level -eq "错误" }).Count
        warning_count = @($bucketEvents | Where-Object { $_.event.level_number -eq 3 -or $_.event.level -eq "Warning" -or $_.event.level -eq "警告" }).Count
        total_count = @($bucketEvents).Count
        samples = @($bucketEvents | Select-Object -First 5 | ForEach-Object {
            [ordered]@{
                time_created = $_.event.time_created
                log_name = $_.event.log_name
                provider = $_.event.provider
                event_id = $_.event.event_id
                level = $_.event.level
                level_number = $_.event.level_number
                matched_provider_patterns = @($_.matched_provider_patterns)
                matched_message_patterns = @($_.matched_message_patterns)
                message_excerpt = Limit-Text -Value $_.event.message -MaxLength 360
            }
        })
        rules = [ordered]@{
            provider_patterns = @($ProviderPatterns)
            message_patterns = @($MessagePatterns)
        }
    }
}

function Test-EventMatchesAnyRule {
    param(
        [object]$Event,
        [object]$BucketRules
    )

    $provider = [string]$Event.provider
    $message = [string]$Event.message
    foreach ($bucketName in $BucketRules.Keys) {
        $rule = $BucketRules[$bucketName]
        foreach ($pattern in $rule.provider_patterns) {
            if ($provider -match $pattern) {
                return $true
            }
        }
        foreach ($pattern in $rule.message_patterns) {
            if ($message -match $pattern) {
                return $true
            }
        }
    }
    return $false
}

function Get-UnclassifiedEventBucket {
    param(
        [object[]]$Events,
        [object]$BucketRules
    )

    $unclassified = @($Events | Where-Object { -not (Test-EventMatchesAnyRule -Event $_ -BucketRules $BucketRules) })
    return [ordered]@{
        error_count = @($unclassified | Where-Object { $_.level_number -eq 2 -or $_.level -eq "Error" -or $_.level -eq "错误" }).Count
        warning_count = @($unclassified | Where-Object { $_.level_number -eq 3 -or $_.level -eq "Warning" -or $_.level -eq "警告" }).Count
        total_count = @($unclassified).Count
        samples = @($unclassified | Select-Object -First 8 | ForEach-Object {
            [ordered]@{
                time_created = $_.time_created
                log_name = $_.log_name
                provider = $_.provider
                event_id = $_.event_id
                level = $_.level
                level_number = $_.level_number
                message_excerpt = Limit-Text -Value $_.message -MaxLength 360
            }
        })
    }
}

function ConvertTo-EventRecord {
    param([object]$Event)

    $message = ""
    try {
        $message = [string]$Event.Message
    } catch {
        $message = ""
    }

    return [ordered]@{
        time_created = if ($Event.TimeCreated) { $Event.TimeCreated.ToString("s") } else { $null }
        log_name = [string]$Event.LogName
        provider = [string]$Event.ProviderName
        event_id = $Event.Id
        level = [string]$Event.LevelDisplayName
        level_number = $Event.Level
        message = $message
    }
}

$generatedAt = Get-Date
$faultTimestamp = $null
if ($FaultTime.Trim()) {
    try {
        $faultTimestamp = [datetime]::Parse($FaultTime)
    } catch {
        throw "FaultTime must be a parseable local datetime, for example 2026-05-14T18:30:00."
    }
}

$logWindowMode = "recent_hours"
$startTime = $generatedAt.AddHours(-1 * $Hours)
$endTime = $generatedAt
if ($faultTimestamp) {
    $logWindowMode = "fault_window"
    $startTime = $faultTimestamp.AddMinutes(-1 * [Math]::Abs($BeforeFaultMinutes))
    $endTime = $faultTimestamp.AddMinutes([Math]::Abs($AfterFaultMinutes))
    if ($endTime -gt $generatedAt) {
        $endTime = $generatedAt
    }
    if ($startTime -gt $endTime) {
        $startTime = $endTime.AddMinutes(-5)
    }
}

Update-ScanProgress "Reading system identity"
$computer = Try-Collect { Get-CimInstance Win32_ComputerSystem } $null "system.computer"
$bios = Try-Collect { Get-CimInstance Win32_BIOS } $null "system.bios"
$baseboard = Try-Collect { Get-CimInstance Win32_BaseBoard } $null "system.baseboard"
$os = Try-Collect { Get-CimInstance Win32_OperatingSystem } $null "system.os"
$processors = @(Try-Collect { Get-CimInstance Win32_Processor } @() "system.processors")

Update-ScanProgress "Reading device inventory"
$pnpDevices = @(Try-Collect { Get-CimInstance Win32_PnPEntity } @() "inventory.pnp_devices")

Update-ScanProgress "Reading recent event logs"
$systemEvents = @(Try-Collect {
    Get-WinEvent -FilterHashtable @{LogName = "System"; StartTime = $startTime; EndTime = $endTime} -ErrorAction Stop |
        Where-Object { $_.Level -in @(2, 3) } |
        Select-Object -First $MaxSystemEvents |
        ForEach-Object { ConvertTo-EventRecord $_ }
} @() "logs.system")

$applicationEvents = @(Try-Collect {
    Get-WinEvent -FilterHashtable @{LogName = "Application"; StartTime = $startTime; EndTime = $endTime} -ErrorAction Stop |
        Where-Object { $_.Level -in @(2, 3) } |
        Select-Object -First $MaxApplicationEvents |
        ForEach-Object { ConvertTo-EventRecord $_ }
} @() "logs.application")

$allEvents = @($systemEvents + $applicationEvents)

$eventBucketRules = [ordered]@{
    power = [ordered]@{
        provider_patterns = @("Kernel-Power", "ACPI", "Battery", "UcmUcsi", "USB", "Kernel-PnP")
        message_patterns = @("battery", "charging", "adapter", "power", "usb-c", "type-c", "ucmucsi")
    }
    storage = [ordered]@{
        provider_patterns = @("Disk", "Ntfs", "storahci", "stornvme", "iaStor")
        message_patterns = @("disk", "ntfs", "bad block", "io error", "I/O")
    }
    memory = [ordered]@{
        provider_patterns = @("BugCheck", "WHEA-Logger", "MemoryDiagnostics")
        message_patterns = @("memory", "page fault", "bugcheck", "WHEA")
    }
    network = [ordered]@{
        provider_patterns = @("WLAN", "Netwtw", "Tcpip", "Bluetooth", "e1", "rt")
        message_patterns = @("wifi", "wi-fi", "wlan", "bluetooth", "adapter", "link", "network")
    }
    display = [ordered]@{
        provider_patterns = @("Display", "nvlddmkm", "igfx", "dxgkrnl", "amdkmdag")
        message_patterns = @("display", "graphics", "gpu", "monitor")
    }
    input = [ordered]@{
        provider_patterns = @("HID", "i8042", "kbd", "mou", "I2C")
        message_patterns = @("keyboard", "touchpad", "hid", "i2c")
    }
    camera = [ordered]@{
        provider_patterns = @("Camera", "FrameServer", "USBVideo")
        message_patterns = @("camera", "webcam")
    }
    audio = [ordered]@{
        provider_patterns = @("Audio", "Realtek", "IntcAudio")
        message_patterns = @("audio", "speaker", "sound")
    }
    usb_io = [ordered]@{
        provider_patterns = @("USB", "UcmUcsi", "Kernel-PnP")
        message_patterns = @("usb", "type-c", "device not recognized", "hub")
    }
    thermal = [ordered]@{
        provider_patterns = @("Thermal", "Kernel-Processor-Power", "Kernel-Power")
        message_patterns = @("thermal", "overheat", "throttle", "fan")
    }
    mainboard = [ordered]@{
        provider_patterns = @("WHEA-Logger", "ACPI", "Kernel-PnP", "PCI")
        message_patterns = @("whea", "acpi", "pci", "firmware")
    }
}

Update-ScanProgress "Reading battery and power data"
$batteryStaticData = @(Try-Collect { Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData } @() "battery.static_data")
$batteryFullChargedCapacity = @(Try-Collect { Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity } @() "battery.full_charged_capacity")
$batteryCycleCount = @(Try-Collect { Get-CimInstance -Namespace root\wmi -ClassName BatteryCycleCount } @() "battery.cycle_count")
$batteryStatusData = @(Try-Collect { Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus } @() "battery.status_data")
$batteries = @(Try-Collect { Get-CimInstance Win32_Battery } @() "battery.win32_battery")
$portableBatteries = @(Try-Collect { Get-CimInstance Win32_PortableBattery } @() "battery.portable_battery")
$powerManagementEvents = @($pnpDevices | Where-Object {
    $_.Name -match "Battery|AC Adapter|Microsoft AC|USB Type-C|UCM-UCSI|Power|Charging|PD Controller"
})
$usbTypeCDevices = @($pnpDevices | Where-Object {
    $_.Name -match "USB Type-C|UCM-UCSI|UCSI|PD Controller|Power Delivery"
})

$designCapacity = if ($batteryStaticData.Count -gt 0) { $batteryStaticData[0].DesignedCapacity } else { $null }
$fullCapacity = if ($batteryFullChargedCapacity.Count -gt 0) { $batteryFullChargedCapacity[0].FullChargedCapacity } else { $null }
$capacityRatio = $null
if ($designCapacity -and $fullCapacity -and $designCapacity -gt 0) {
    $capacityRatio = [Math]::Round(($fullCapacity / $designCapacity), 4)
}
$cycleCount = if ($batteryCycleCount.Count -gt 0) { $batteryCycleCount[0].CycleCount } else { $null }
$batteryStatus = if ($batteryStatusData.Count -gt 0) { $batteryStatusData[0] } else { $null }
$chargeRate = if ($batteryStatus -and $batteryStatus.ChargeRate -ne $null) { $batteryStatus.ChargeRate } else { $null }
$dischargeRate = if ($batteryStatus -and $batteryStatus.DischargeRate -ne $null) { $batteryStatus.DischargeRate } else { $null }
$batteryVoltage = if ($batteryStatus -and $batteryStatus.Voltage -ne $null) { $batteryStatus.Voltage } else { $null }
$batteryPowerOnline = if ($batteryStatus -and $batteryStatus.PowerOnline -ne $null) { ConvertTo-BoolOrNull $batteryStatus.PowerOnline } else { $null }
$batteryCharging = if ($batteryStatus -and $batteryStatus.Charging -ne $null) { ConvertTo-BoolOrNull $batteryStatus.Charging } else { $null }
$batteryDischarging = if ($batteryStatus -and $batteryStatus.Discharging -ne $null) { ConvertTo-BoolOrNull $batteryStatus.Discharging } else { $null }
$acLineStatus = if ($batteryPowerOnline -ne $null) {
    $batteryPowerOnline
} elseif ($batteries.Count -gt 0) {
    switch ([int]$batteries[0].BatteryStatus) {
        2 { $true }
        6 { $true }
        7 { $true }
        8 { $true }
        9 { $true }
        11 { $true }
        default { $false }
    }
} else {
    $null
}

Update-ScanProgress "Reading storage and memory data"
$physicalDisks = @(Try-Collect { Get-CimInstance Win32_DiskDrive } @() "storage.disk_drive")
$physicalDiskHealth = @(Try-Collect { Get-PhysicalDisk } @() "storage.physical_disk_health")
$storageReliability = @(Try-Collect { Get-PhysicalDisk | Get-StorageReliabilityCounter } @() "storage.reliability_counter")
$logicalDisks = @(Try-Collect { Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" } @() "storage.logical_disks")

$memoryModules = @(Try-Collect { Get-CimInstance Win32_PhysicalMemory } @() "memory.physical_memory")

Update-ScanProgress "Reading network data"
$netAdapters = @(Try-Collect { Get-NetAdapter | Where-Object { $_.Status -ne $null -and -not (Test-IsVirtualNetworkAdapter $_) } } @() "network.adapters")
$netStats = @(Try-Collect { Get-NetAdapterStatistics } @() "network.statistics")
$wlanText = Try-Collect { netsh wlan show interfaces | Out-String } "" "network.wlan_interfaces"
$wlanSignal = $null
if ($wlanText -match "Signal\s*:\s*(\d+)%") {
    $wlanSignal = [int]$Matches[1]
}

Update-ScanProgress "Reading display and input data"
$videoControllers = @(Try-Collect { Get-CimInstance Win32_VideoController } @() "display.video_controllers")
$monitorDevices = @($pnpDevices | Where-Object {
    ($_.PNPClass -eq "Monitor" -or $_.Name -match "Monitor|Display|Panel") -and
    -not (Test-IsVirtualDeviceName $_.Name)
})
$keyboardDevices = @(Try-Collect { Get-CimInstance Win32_Keyboard } @() "input.keyboards")
$touchpadDevices = @($pnpDevices | Where-Object { $_.Name -match "Touchpad|Trackpad|I2C HID" })

Update-ScanProgress "Reading camera, audio, USB, and thermal data"
$cameraDevices = @($pnpDevices | Where-Object { $_.Name -match "Camera|Webcam|Integrated Camera|USB2\.0 HD UVC|UVC Camera" })
$audioDevices = @(Try-Collect { Get-CimInstance Win32_SoundDevice } @() "audio.sound_devices")
$usbControllers = @(Try-Collect { Get-CimInstance Win32_USBController } @() "usb.controllers")
$usbProblemDevices = @($pnpDevices | Where-Object { $_.PNPClass -match "USB" -and $_.ConfigManagerErrorCode -ne 0 })
$problemDevices = @($pnpDevices | Where-Object { $_.ConfigManagerErrorCode -ne 0 })

$thermalZones = @(Try-Collect { Get-CimInstance -Namespace root\wmi -ClassName MSAcpi_ThermalZoneTemperature } @() "thermal.acpi_zones")

Update-ScanProgress "Reading crash dump metadata"
$minidumpFiles = @(Try-Collect {
    Get-ChildItem -Path "C:\Windows\Minidump" -Filter "*.dmp" -ErrorAction Stop |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10
} @() "crash_dump.minidump")
$memoryDumpFile = Try-Collect {
    Get-Item -Path "C:\Windows\MEMORY.DMP" -ErrorAction Stop
} $null "crash_dump.memory_dump"

Update-ScanProgress "Building runtime information JSON"
$runtime = [ordered]@{
    schema_version = "1.0"
    generated_at = $generatedAt.ToString("s")
    window_hours = $Hours
    collection_status = $script:CollectionStatus
    collection_baseline = [ordered]@{
        version = "1.0"
        strategy = "FRU evidence baseline"
        layers = @("inventory", "metrics", "logs", "active_tests")
        required_runtime_sections = @(
            "system",
            "bios",
            "mainboard",
            "battery",
            "power",
            "storage",
            "memory",
            "network",
            "display",
            "input",
            "camera",
            "audio",
            "usb",
            "thermal",
            "performance",
            "device_inventory",
            "events",
            "tests"
        )
        fru_scope = [ordered]@{
            power = @("power_adapter", "battery_pack", "motherboard charging path")
            storage = @("m2_ssd_module")
            compute = @("ram_module", "motherboard CPU/GPU path")
            communication = @("wlan_module", "bluetooth logical adapter")
            thermal = @("fan_module", "heat_sink")
            display = @("display_panel_module", "motherboard GPU path")
            input = @("keyboard_module", "touchpad_module")
            sensor = @("camera_module")
            interface = @("speaker_module", "led_board", "io_board")
            mainboard = @("motherboard")
        }
    }
    system = [ordered]@{
        computer_name = $env:COMPUTERNAME
        manufacturer = if ($computer) { $computer.Manufacturer } else { $null }
        model = if ($computer) { $computer.Model } else { $null }
        pc_system_type = if ($computer) { $computer.PCSystemType } else { $null }
        os_caption = if ($os) { $os.Caption } else { $null }
        os_version = if ($os) { $os.Version } else { $null }
        last_boot_time = if ($os -and $os.LastBootUpTime) { $os.LastBootUpTime.ToString("s") } else { $null }
    }
    bios = [ordered]@{
        version = if ($bios) { ($bios.SMBIOSBIOSVersion -join " ") } else { $null }
        release_date = if ($bios -and $bios.ReleaseDate) { $bios.ReleaseDate.ToString("s") } else { $null }
    }
    mainboard = [ordered]@{
        present = $null -ne $baseboard
        manufacturer = if ($baseboard) { $baseboard.Manufacturer } else { $null }
        product = if ($baseboard) { $baseboard.Product } else { $null }
    }
    battery = [ordered]@{
        present = $batteries.Count -gt 0
        estimated_charge_remaining = if ($batteries.Count -gt 0) { $batteries[0].EstimatedChargeRemaining } else { $null }
        battery_status = if ($batteries.Count -gt 0) { $batteries[0].BatteryStatus } else { $null }
        status = if ($batteries.Count -gt 0) { $batteries[0].Status } else { $null }
        design_capacity_mwh = $designCapacity
        full_charged_capacity_mwh = $fullCapacity
        full_charge_capacity_ratio = $capacityRatio
        cycle_count = $cycleCount
        voltage_millivolts = $batteryVoltage
        charge_rate = $chargeRate
        discharge_rate = $dischargeRate
        charging = $batteryCharging
        discharging = $batteryDischarging
    }
    power = [ordered]@{
        ac_line_status = $acLineStatus
        source = if ($acLineStatus -eq $true) { "AC" } elseif ($acLineStatus -eq $false -and $batteries.Count -gt 0) { "Battery" } else { $null }
        adapter_wattage = $null
        usb_c_pd_status = if ($usbTypeCDevices.Count -gt 0) { "present" } else { $null }
        power_online = $batteryPowerOnline
        charging = $batteryCharging
        discharging = $batteryDischarging
        charge_rate = $chargeRate
        discharge_rate = $dischargeRate
        voltage_millivolts = $batteryVoltage
        portable_battery_count = $portableBatteries.Count
        power_device_count = $powerManagementEvents.Count
        power_devices = @($powerManagementEvents | Select-Object -First 20 | ForEach-Object { ConvertTo-StatusObject $_ })
        usb_c_power_devices = @($usbTypeCDevices | Select-Object -First 20 | ForEach-Object { ConvertTo-StatusObject $_ })
    }
    storage = [ordered]@{
        drives = @($physicalDisks | ForEach-Object {
            $disk = $_
            $health = @($physicalDiskHealth | Where-Object { $_.FriendlyName -eq $disk.Model } | Select-Object -First 1)
            $reliability = @($storageReliability | Select-Object -First 1)
            [ordered]@{
                present = $true
                model = $disk.Model
                interface_type = $disk.InterfaceType
                size_bytes = [int64]$disk.Size
                status = $disk.Status
                health_status = if ($health.Count -gt 0) { $health[0].HealthStatus.ToString() } else { $null }
                operational_status = if ($health.Count -gt 0) { ($health[0].OperationalStatus -join ",") } else { $null }
                temperature_celsius = if ($reliability.Count -gt 0) { $reliability[0].Temperature } else { $null }
                wear = if ($reliability.Count -gt 0) { $reliability[0].Wear } else { $null }
            }
        })
        volumes = @($logicalDisks | ForEach-Object {
            $freePercent = $null
            if ($_.Size -and $_.Size -gt 0) {
                $freePercent = [Math]::Round(($_.FreeSpace / $_.Size) * 100, 2)
            }
            [ordered]@{
                device_id = $_.DeviceID
                size_bytes = [int64]$_.Size
                free_bytes = [int64]$_.FreeSpace
                free_percent = $freePercent
            }
        })
    }
    memory = [ordered]@{
        total_physical_bytes = if ($computer) { [int64]$computer.TotalPhysicalMemory } else { $null }
        available_bytes = if ($os) { [int64]$os.FreePhysicalMemory * 1024 } else { $null }
        modules = @($memoryModules | ForEach-Object {
            [ordered]@{
                present = $true
                locator = $_.DeviceLocator
                capacity_bytes = [int64]$_.Capacity
                speed_mhz = $_.Speed
                manufacturer = $_.Manufacturer
            }
        })
    }
    network = [ordered]@{
        wlan = [ordered]@{
            signal_percent = $wlanSignal
        }
        adapters = @($netAdapters | ForEach-Object {
            $adapter = $_
            $stat = @($netStats | Where-Object { $_.Name -eq $adapter.Name } | Select-Object -First 1)
            [ordered]@{
                present = $true
                name = $adapter.Name
                interface_description = $adapter.InterfaceDescription
                status = $adapter.Status
                link_speed = $adapter.LinkSpeed
                received_packet_errors = if ($stat.Count -gt 0) { $stat[0].ReceivedPacketErrors } else { $null }
                outbound_discarded_packets = if ($stat.Count -gt 0) { $stat[0].OutboundDiscardedPackets } else { $null }
            }
        })
    }
    display = [ordered]@{
        adapters = @($videoControllers | ForEach-Object {
            [ordered]@{
                name = $_.Name
                status = $_.Status
                driver_version = $_.DriverVersion
                video_processor = $_.VideoProcessor
            }
        })
        monitors = @($monitorDevices | ForEach-Object { ConvertTo-StatusObject $_ })
    }
    input = [ordered]@{
        keyboards = @($keyboardDevices | ForEach-Object {
            [ordered]@{
                present = $true
                name = $_.Name
                status = $_.Status
            }
        })
        touchpad_devices = @($touchpadDevices | ForEach-Object { ConvertTo-StatusObject $_ })
    }
    camera = [ordered]@{
        devices = @($cameraDevices | ForEach-Object { ConvertTo-StatusObject $_ })
    }
    audio = [ordered]@{
        devices = @($audioDevices | ForEach-Object {
            [ordered]@{
                present = $true
                name = $_.Name
                status = $_.Status
                manufacturer = $_.Manufacturer
            }
        })
    }
    usb = [ordered]@{
        controllers = @($usbControllers | ForEach-Object {
            [ordered]@{
                present = $true
                name = $_.Name
                status = $_.Status
            }
        })
        problem_devices = @($usbProblemDevices | ForEach-Object { ConvertTo-StatusObject $_ })
    }
    thermal = [ordered]@{
        thermal_zone_count = $thermalZones.Count
        zones = @($thermalZones | ForEach-Object {
            $temperature = $null
            if ($_.CurrentTemperature) {
                $temperature = [Math]::Round(($_.CurrentTemperature / 10) - 273.15, 2)
            }
            [ordered]@{
                instance_name = $_.InstanceName
                temperature_celsius = $temperature
            }
        })
    }
    performance = [ordered]@{
        cpu_load_percent = if ($processors.Count -gt 0) { [Math]::Round((($processors | Measure-Object -Property LoadPercentage -Average).Average), 2) } else { $null }
    }
    device_inventory = [ordered]@{
        problem_device_count = $problemDevices.Count
        problem_devices = @($problemDevices | Select-Object -First 50 | ForEach-Object { ConvertTo-StatusObject $_ })
    }
    crash_dump = [ordered]@{
        available = (($minidumpFiles.Count -gt 0) -or ($null -ne $memoryDumpFile))
        source = "self_after_reboot"
        dump_files = @(
            @($minidumpFiles | ForEach-Object {
                [ordered]@{
                    kind = "minidump"
                    path = $_.FullName
                    size_bytes = $_.Length
                    modified_at = $_.LastWriteTime.ToString("s")
                }
            }) +
            @(
                if ($memoryDumpFile) {
                    [ordered]@{
                        kind = "memory_dump"
                        path = $memoryDumpFile.FullName
                        size_bytes = $memoryDumpFile.Length
                        modified_at = $memoryDumpFile.LastWriteTime.ToString("s")
                    }
                }
            )
        )
        minidumps = @($minidumpFiles | ForEach-Object {
            [ordered]@{
                path = $_.FullName
                size_bytes = $_.Length
                modified_at = $_.LastWriteTime.ToString("s")
            }
        })
        memory_dump = if ($memoryDumpFile) {
            [ordered]@{
                path = $memoryDumpFile.FullName
                size_bytes = $memoryDumpFile.Length
                modified_at = $memoryDumpFile.LastWriteTime.ToString("s")
            }
        } else {
            @{}
        }
        bugcheck_code = ""
        probable_modules = @()
        limitation = if (($minidumpFiles.Count -gt 0) -or ($null -ne $memoryDumpFile)) { "" } else { "No minidump or MEMORY.DMP metadata was found after reboot." }
        reason = if (($minidumpFiles.Count -gt 0) -or ($null -ne $memoryDumpFile)) { "" } else { "dump_not_found_or_machine_unavailable" }
        next_action = if (($minidumpFiles.Count -gt 0) -or ($null -ne $memoryDumpFile)) { "" } else { "enable_dump_or_collect_offline_evidence" }
    }
    events = [ordered]@{
        total_warning_error_count = $allEvents.Count
        collection = [ordered]@{
            mode = $logWindowMode
            fault_time = if ($faultTimestamp) { $faultTimestamp.ToString("s") } else { $null }
            start_time = $startTime.ToString("s")
            end_time = $endTime.ToString("s")
            before_fault_minutes = if ($faultTimestamp) { [Math]::Abs($BeforeFaultMinutes) } else { $null }
            after_fault_minutes = if ($faultTimestamp) { [Math]::Abs($AfterFaultMinutes) } else { $null }
            max_system_events = $MaxSystemEvents
            max_application_events = $MaxApplicationEvents
            logs = @("System", "Application")
            level_filter = @("Error", "Warning")
            system_event_count = $systemEvents.Count
            application_event_count = $applicationEvents.Count
        }
        power = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.power.provider_patterns -MessagePatterns $eventBucketRules.power.message_patterns
        storage = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.storage.provider_patterns -MessagePatterns $eventBucketRules.storage.message_patterns
        memory = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.memory.provider_patterns -MessagePatterns $eventBucketRules.memory.message_patterns
        network = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.network.provider_patterns -MessagePatterns $eventBucketRules.network.message_patterns
        display = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.display.provider_patterns -MessagePatterns $eventBucketRules.display.message_patterns
        input = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.input.provider_patterns -MessagePatterns $eventBucketRules.input.message_patterns
        camera = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.camera.provider_patterns -MessagePatterns $eventBucketRules.camera.message_patterns
        audio = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.audio.provider_patterns -MessagePatterns $eventBucketRules.audio.message_patterns
        usb_io = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.usb_io.provider_patterns -MessagePatterns $eventBucketRules.usb_io.message_patterns
        thermal = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.thermal.provider_patterns -MessagePatterns $eventBucketRules.thermal.message_patterns
        mainboard = Get-EventBucket -Events $allEvents -ProviderPatterns $eventBucketRules.mainboard.provider_patterns -MessagePatterns $eventBucketRules.mainboard.message_patterns
        unclassified = Get-UnclassifiedEventBucket -Events $allEvents -BucketRules $eventBucketRules
    }
    tests = [ordered]@{
        power = [ordered]@{ adapter_detected = "not_run"; discharge_test_result = "not_run" }
        storage = [ordered]@{ short_self_test = "not_run"; read_write_test = "not_run" }
        memory = [ordered]@{ extended_test_result = "not_run" }
        network = [ordered]@{ ping_gateway_result = "not_run"; bluetooth_pairing_result = "not_run" }
        thermal = [ordered]@{ fan_response_result = "not_run"; load_temperature_curve = "not_run" }
        display = [ordered]@{ external_ok_internal_failed = "not_run"; pixel_or_backlight_result = "not_run" }
        camera = [ordered]@{ capture_result = "not_run" }
        input = [ordered]@{ keyboard_matrix_result = "not_run"; touchpad_gesture_result = "not_run" }
        audio = [ordered]@{ left_right_speaker_result = "not_run" }
        led = [ordered]@{ visual_result = "not_run" }
        io = [ordered]@{ usb_port_result = "not_run"; audio_jack_result = "not_run"; lan_port_result = "not_run" }
        mainboard = [ordered]@{ multi_bus_stress_result = "not_run" }
    }
}

Update-ScanProgress "Writing runtime information"
$output = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath
} else {
    Join-Path (Resolve-Path -Path ".").Path $OutputPath
}
$outputDir = Split-Path -Parent $output
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$runtime | ConvertTo-Json -Depth 12 | Set-Content -Path $output -Encoding UTF8
$scanTimer.Stop()
if (-not $NoProgress) {
    Write-Progress -Activity $script:ProgressActivity -Completed
}

Write-Output "Runtime information collected."
Write-Output "Window hours: $Hours"
Write-Output "Max system events: $MaxSystemEvents"
Write-Output "Max application events: $MaxApplicationEvents"
Write-Output "Output: $output"
Write-Output "Warning/error events: $($allEvents.Count)"
Write-Output "Problem devices: $($problemDevices.Count)"
Write-Output "Elapsed seconds: $([Math]::Round($scanTimer.Elapsed.TotalSeconds, 2))"
