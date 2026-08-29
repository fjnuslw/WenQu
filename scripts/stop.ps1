# stop.ps1 — 停止 api / agents / web（默认不动 docker；-Docker 同时停基础设施）
# 用法：stop.bat 双击运行；powershell -File scripts\stop.ps1 [-Docker]

param([switch]$Docker)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")

Ensure-RuntimeDirs
Write-Host "=== get_offer 停止 ===" -ForegroundColor White
$services = @(
    @{ Name = "web";    Port = $Script:Defaults.WebPort },
    @{ Name = "agents"; Port = $Script:Defaults.AgentsPort },
    @{ Name = "api";    Port = $Script:Defaults.ApiPort }
)
$ourProcessNames = @("python", "node", "cmd", "npm")

foreach ($service in $services) {
    $name = $service.Name
    $procId = Read-ProcId $name
    if ($null -ne $procId -and (Test-ProcAlive $procId)) {
        Write-Host "==> 停止 $name (pid $procId)"
        if (Stop-ProcTree $procId) { Write-Ok "$name 已停止" }
        else { Write-Warn2 "taskkill 返回失败（进程可能已退出）" }
    } elseif ($null -ne $procId) {
        Write-Warn2 "$name 的 pid $procId 已不存在（可能是异常退出），清理 pid 文件"
    } else {
        Write-Host "==> $name 无 pid 记录"
    }
    Remove-ProcIdFile $name

    # 兜底：若端口仍被监听，检查占用者是否是我们的进程再杀，绝不误伤无关程序
    $owners = Get-ListeningProcIds $service.Port
    foreach ($owner in $owners) {
        $ownerName = Get-PortOwnerName $owner
        if ($ourProcessNames -contains $ownerName.ToLower()) {
            Write-Warn2 "$name 端口 $($service.Port) 仍被 $ownerName(pid $owner) 占用，强制结束"
            Stop-ProcTree $owner | Out-Null
        } else {
            Write-Warn2 "端口 $($service.Port) 被非本项目进程 $ownerName(pid $owner) 占用，不动它"
        }
    }
}

if ($Docker) {
    Write-Host "==> 停止基础设施（docker compose stop）"
    Push-Location (Get-RepoRoot)
    try { docker compose stop | ForEach-Object { Write-Host "  $_" } } finally { Pop-Location }
} else {
    Write-Host "==> docker 基础设施保持运行（如需一并停止：powershell -File scripts\stop.ps1 -Docker）"
}
Write-Host "=== 停止完成 ===" -ForegroundColor White
