# status.ps1 — 各服务与基础设施状态一览

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")

Ensure-RuntimeDirs
Write-Host "=== get_offer 状态 ===" -ForegroundColor White
$services = @(
    @{ Name = "api";    Health = "/api/health"; Port = $Script:Defaults.ApiPort },
    @{ Name = "agents"; Health = "/health";     Port = $Script:Defaults.AgentsPort },
    @{ Name = "web";    Health = "/";           Port = $Script:Defaults.WebPort }
)
foreach ($service in $services) {
    $name = $service.Name
    $procId = Read-ProcId $name
    $pidText = "-"
    $alive = $false
    if ($null -ne $procId) {
        $alive = Test-ProcAlive $procId
        $pidText = "$procId"
    }
    $portText = "$($service.Port)"
    if (-not $alive -and (Test-PortListening $service.Port)) { $portText = "$($service.Port)(被其他进程占用)" }
    $healthText = "未运行"
    if ($alive) {
        $url = "http://127.0.0.1:$($service.Port)$($service.Health)"
        if (Test-HttpOk $url) { $healthText = "健康" } else { $healthText = "无响应" }
    }
    $aliveText = if ($alive) { "运行中" } else { "已停止" }
    Write-Host ("  {0,-8} pid {1,-8} {2,-6} 端口 {3,-24} {4}" -f $name, $pidText, $aliveText, $portText, $healthText)
}

Write-Host ""
Write-Host "基础设施（docker compose）:"
Push-Location (Get-RepoRoot)
try {
    docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "docker 不可用或未启动" }
} finally { Pop-Location }

$apiKey = Get-DotEnvValue (Join-Path (Get-RepoRoot) "apps\api\.env") "GETOFFER_LLM__API_KEY"
# agents 的真实密钥状态以运行时为准（.env 或系统环境变量均可配置），健康端点会回报 keyConfigured
$agentsKeyText = "未知"
try {
    $agentsHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$($Script:Defaults.AgentsPort)/health" -TimeoutSec 3
    $agentsKeyText = if ($agentsHealth.keyConfigured) { "已配置（运行时确认）" } else { "未配置（运行时确认）" }
} catch {
    $fileKey = Get-DotEnvValue (Join-Path (Get-RepoRoot) "apps\agents\.env") "DEEPSEEK_API_KEY"
    $agentsKeyText = if ([string]::IsNullOrEmpty($fileKey)) { "未填写（服务未运行，仅查文件）" } else { "已填写（仅查文件）" }
}
Write-Host ""
Write-Host ("密钥: api GETOFFER_LLM__API_KEY {0} | agents DEEPSEEK_API_KEY {1}" -f `
    $(if ([string]::IsNullOrEmpty($apiKey)) { "未填写" } else { "已填写" }), $agentsKeyText)
