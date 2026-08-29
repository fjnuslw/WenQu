# common.ps1 — 共享配置与助手（Windows PowerShell 5.1 兼容）
# 端口策略（用户要求）：默认使用冷门段，启动前逐一探测占用；被占用则向上寻找下一个空闲端口。

$ErrorActionPreference = "Stop"

$Script:RepoRoot = Split-Path -Parent $PSScriptRoot
$Script:LogsDir = Join-Path $RepoRoot "logs"
$Script:RunDir = Join-Path $RepoRoot "data\run"

$Script:Defaults = @{
    ApiPort      = 23480
    AgentsPort   = 23481
    WebPort      = 23482
    PostgresPort = 24432
    MeiliPort    = 27700
    RedisPort    = 26379
}

function Get-RepoRoot { $Script:RepoRoot }
function Get-LogsDir { $Script:LogsDir }
function Get-RunDir { $Script:RunDir }

function Ensure-RuntimeDirs {
    foreach ($dir in @($Script:LogsDir, $Script:RunDir)) {
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    }
}

function Get-OccupiedTcpPorts {
    [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
        ForEach-Object { [int]$_.Port } |
        Sort-Object -Unique
}

function Test-PortListening([int]$Port) {
    $occupied = Get-OccupiedTcpPorts
    return ($occupied -contains $Port)
}

# 返回一个空闲端口：从 preferred 起向上扫描，跳过已占用与已分配给兄弟服务的端口。
function Find-FreePort([int]$Preferred, [System.Collections.Generic.List[int]]$Taken) {
    $candidate = $Preferred
    for ($i = 0; $i -lt 200; $i++) {
        $occupiedBySystem = Test-PortListening $candidate
        if (-not $occupiedBySystem -and -not ($Taken -contains $candidate)) {
            return $candidate
        }
        $candidate++
    }
    throw "在 $Preferred 起的 200 个端口内未找到空闲端口"
}

function Test-HttpOk([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-HttpOk([string]$Url, [int]$TimeoutSec) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk $Url) { return $true }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Test-ProcAlive([int]$ProcId) {
    return ($null -ne (Get-Process -Id $ProcId -ErrorAction SilentlyContinue))
}

function Save-ProcId([string]$Name, [int]$ProcId) {
    Set-Content -Path (Join-Path $Script:RunDir "$Name.pid") -Value $ProcId -Encoding ASCII
}

function Read-ProcId([string]$Name) {
    $file = Join-Path $Script:RunDir "$Name.pid"
    if (Test-Path $file) {
        $text = (Get-Content $file -ErrorAction SilentlyContinue | Select-Object -First 1)
        $parsed = 0
        if ([int]::TryParse($text, [ref]$parsed)) { return $parsed }
    }
    return $null
}

function Remove-ProcIdFile([string]$Name) {
    $file = Join-Path $Script:RunDir "$Name.pid"
    if (Test-Path $file) { Remove-Item $file -Force }
}

function Stop-ProcTree([int]$ProcId) {
    & taskkill /PID $ProcId /T /F | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-ListeningProcIds([int]$Port) {
    try {
        return (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } catch {
        return @()
    }
}

function Get-PortOwnerName([int]$ProcId) {
    $proc = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if ($proc) { return $proc.ProcessName } else { return "unknown" }
}

# 读取 .env 中某 key 的值（apps/*/​.env，KEY=VALUE；找不到返回 $null）
function Get-DotEnvValue([string]$EnvFile, [string]$Key) {
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($raw in (Get-Content $EnvFile)) {
        $line = $raw.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { continue }
        $idx = $line.IndexOf("=")
        if ($idx -le 0) { continue }
        if ($line.Substring(0, $idx).Trim() -eq $Key) {
            $value = $line.Substring($idx + 1).Trim()
            if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }
    return $null
}

function Test-CommandExists([string]$Name) {
    return ($null -ne (Get-Command $Name -ErrorAction SilentlyContinue))
}

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message) { Write-Host "  [!!] $Message" -ForegroundColor Yellow }
function Write-Fail([string]$Message) { Write-Host "  [XX] $Message" -ForegroundColor Red }
