param(
    [string]$OutputPath = "data\bsod_info.json",
    [int]$RecentDays = 30,
    [int]$MaxEvents = 200
)

$ErrorActionPreference = "Stop"

function ConvertTo-EventObject {
    param([object]$Event)
    [ordered]@{
        time_created = if ($Event.TimeCreated) { $Event.TimeCreated.ToString("s") } else { $null }
        provider = $Event.ProviderName
        event_id = $Event.Id
        level = $Event.LevelDisplayName
        message_excerpt = (($Event.Message -replace "\s+", " ").Trim())
    }
}

$startTime = (Get-Date).AddDays(-1 * [Math]::Abs($RecentDays))
$minidumpDir = Join-Path $env:SystemRoot "Minidump"
$memoryDump = Join-Path $env:SystemRoot "MEMORY.DMP"

$dumpFiles = @()
if (Test-Path $minidumpDir) {
    $dumpFiles += Get-ChildItem -Path $minidumpDir -Filter *.dmp -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 20 |
        ForEach-Object {
            [ordered]@{
                path = $_.FullName
                name = $_.Name
                size_bytes = $_.Length
                last_write_time = $_.LastWriteTime.ToString("s")
            }
        }
}

$systemEvents = @(Get-WinEvent -FilterHashtable @{
    LogName = "System"
    StartTime = $startTime
} -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Id -in @(41, 1001, 6008, 18, 19, 46, 47) -or
        $_.ProviderName -match "BugCheck|WHEA|Kernel-Power"
    } |
    Sort-Object TimeCreated -Descending |
    Select-Object -First $MaxEvents)

$installedDrivers = @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Sort-Object DriverDate -Descending |
    Select-Object -First 50 DeviceName, DriverProviderName, DriverVersion, DriverDate, InfName)

$result = [ordered]@{
    generated_at = (Get-Date).ToString("s")
    collection = [ordered]@{
        recent_days = $RecentDays
        max_events = $MaxEvents
        minidump_dir = $minidumpDir
        memory_dump_path = $memoryDump
    }
    minidumps = @($dumpFiles)
    memory_dump = [ordered]@{
        present = Test-Path $memoryDump
        path = $memoryDump
        size_bytes = if (Test-Path $memoryDump) { (Get-Item $memoryDump).Length } else { $null }
        last_write_time = if (Test-Path $memoryDump) { (Get-Item $memoryDump).LastWriteTime.ToString("s") } else { $null }
    }
    crash_events = @($systemEvents | ForEach-Object { ConvertTo-EventObject $_ })
    recent_drivers = @($installedDrivers | ForEach-Object {
        [ordered]@{
            device_name = $_.DeviceName
            provider = $_.DriverProviderName
            version = $_.DriverVersion
            driver_date = if ($_.DriverDate) { ([datetime]$_.DriverDate).ToString("s") } else { $null }
            inf_name = $_.InfName
        }
    })
    note = "This collector gathers BSOD evidence metadata. Use WinDbg !analyze -v separately for full stack analysis."
}

$target = Resolve-Path -Path (Split-Path -Parent $OutputPath) -ErrorAction SilentlyContinue
if (-not $target) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null
}
$result | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputPath -Encoding UTF8
Write-Host "BSOD evidence written to $OutputPath"
