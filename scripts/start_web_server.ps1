param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8780,
    [string]$PythonPath = "D:\workspace\python3.12.3\python.exe"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$reportsDir = Join-Path $projectRoot "reports"
$locksDir = Join-Path $reportsDir "locks"
New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null
New-Item -ItemType Directory -Force -Path $locksDir | Out-Null

$dashboardProcesses = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" |
    Where-Object {
        $_.CommandLine -match "fru_web_server\.py" -or
        (($_.CommandLine -match "(^|\\s|\\)main\.py(\\s|$)") -and $_.CommandLine -match [regex]::Escape($projectRoot))
    }

foreach ($process in $dashboardProcesses) {
    Stop-Process -Id $process.ProcessId -Force
}

Start-Sleep -Seconds 1
Remove-Item -Path (Join-Path $locksDir "web_*.lock") -Force -ErrorAction SilentlyContinue

if (-not (Test-Path $PythonPath)) {
    $PythonPath = "python"
}

$outLog = Join-Path $reportsDir "web_server_$Port.out.log"
$errLog = Join-Path $reportsDir "web_server_$Port.err.log"

$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList @("-u", "fru_web_server.py", "--host", $HostName, "--port", "$Port") `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 1
$appUrl = "http://${HostName}:${Port}/"
$healthUrl = "http://${HostName}:${Port}/api/health"

try {
    $health = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 5
    if ($health.StatusCode -ne 200) {
        throw "Unexpected health status: $($health.StatusCode)"
    }
} catch {
    throw "Web server started as pid $($process.Id), but health check failed at $healthUrl. $($_.Exception.Message)"
}

[PSCustomObject]@{
    Pid = $process.Id
    DashboardUrl = $appUrl
    HealthCheckUrl = $healthUrl
    OpenThisInBrowser = $appUrl
    OutLog = $outLog
    ErrLog = $errLog
}
