# start.ps1 — 一键启动（docker 基础设施 → api → agents → web）
# 用法：start.bat 双击运行，或 powershell -File scripts\start.ps1 [-NoDocker] [-Dev]
# 端口策略：默认冷门段，逐一探测占用，冲突自动向上顺延并回写 web/.env.local。
# 默认 web 走生产模式（next build + next start，路由预编译、切换不卡）；-Dev 保留开发模式。

param(
    [switch]$NoDocker,
    [switch]$Dev
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

Ensure-RuntimeDirs
$repoRoot = Get-RepoRoot
$logDir = Get-LogsDir

Write-Host "=== get_offer 启动 ===" -ForegroundColor White
Write-Host "仓库根目录: $repoRoot"

# ---- 0. 前置检查 ----
Write-Step "前置检查"
if (-not (Test-CommandExists "node")) { Write-Fail "未找到 node，请先安装 Node.js 20+"; exit 1 }
if (-not (Test-CommandExists "npm")) { Write-Fail "未找到 npm"; exit 1 }
if (-not (Test-CommandExists "docker")) { Write-Fail "未找到 docker，请安装 Docker Desktop"; exit 1 }
if (-not $NoDocker) {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { Write-Fail "Docker 守护进程未运行，请先启动 Docker Desktop"; exit 1 }
    Write-Ok "docker 守护进程在线"
}
$apiVenvPython = Join-Path $repoRoot "apps\api\.venv\Scripts\python.exe"
if (-not (Test-Path $apiVenvPython)) {
    Write-Fail "缺少 apps\api\.venv —— 请先双击运行 setup.bat（或 scripts\setup.ps1）"
    exit 1
}
if (-not (Test-Path (Join-Path $repoRoot "apps\agents\node_modules"))) {
    Write-Fail "缺少 apps\agents\node_modules —— 请先运行 setup.bat"
    exit 1
}
if (-not (Test-Path (Join-Path $repoRoot "apps\web\node_modules"))) {
    Write-Fail "缺少 apps\web\node_modules —— 请先运行 setup.bat"
    exit 1
}
Write-Ok "工具链与依赖就绪"

# ---- 1. 端口绑定（固定冷门段；先清本项目残留与孤儿进程，再检测外部占用——不做自动漂移） ----
Write-Step "端口绑定（固定冷门段，启动前清障）"
$apiPort = $Script:Defaults.ApiPort
$agentsPort = $Script:Defaults.AgentsPort
$webPort = $Script:Defaults.WebPort

# 项目级残留清障：命令行指向本项目 apps/* 的残留 node/python 一律结束。
# （历次重启的孤儿 tsx watch / uvicorn 会造成双实例并存、数据目录错位）
function Clear-ProjectStrays {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*get_offer*apps*agents*" -or $_.CommandLine -like "*get_offer*apps*api*" -or $_.CommandLine -like "*get_offer*apps*web*") }
    foreach ($proc in $procs) {
        $name = (Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue).ProcessName
        if (@("python", "node", "cmd", "npm", "tsx") -contains $name) {
            Write-Warn2 "清理残留进程 $name(pid $($proc.ProcessId))"
            taskkill /PID $proc.ProcessId /T /F | Out-Null
        }
    }
}
Clear-ProjectStrays
Start-Sleep -Milliseconds 500

# 端口清障：目标端口若被本项目进程（python/node/cmd/npm）占用则结束之，
# 防止 Next16 单实例锁 / EADDRINUSE 导致新实例静默退出。
function Clear-OurPort([int]$Port) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $ownerPid = $conn.OwningProcess
        $ownerName = (Get-Process -Id $ownerPid -ErrorAction SilentlyContinue).ProcessName
        if (@("python", "node", "cmd", "npm") -contains $ownerName) {
            Write-Warn2 "端口 $Port 上残留本项目进程 $ownerName(pid $ownerPid)，先结束"
            taskkill /PID $ownerPid /T /F | Out-Null
        }
    }
}
Clear-OurPort $apiPort; Clear-OurPort $agentsPort; Clear-OurPort $webPort

# 外部占用显式失败（不做自动漂移，避免代理目标漂移）
foreach ($pair in @(@("api", $apiPort), @("agents", $agentsPort), @("web", $webPort))) {
    if (Test-PortListening $pair[1]) {
        $ownerPid = (Get-NetTCPConnection -LocalPort $pair[1] -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
        $ownerName = if ($ownerPid) { Get-PortOwnerName $ownerPid } else { "unknown" }
        Write-Fail "端口 $($pair[1]) 被外部进程 $ownerName(pid $ownerPid) 占用——请释放后重试"
        exit 1
    }
}
Write-Ok "api = $apiPort, agents = $agentsPort, web = $webPort"
$failures = 0

# ---- 2. 基础设施 ----
if ($NoDocker) {
    Write-Warn2 "跳过 docker（-NoDocker）；请自行保证 postgres/meilisearch/redis 可达"
} else {
    Write-Step "启动基础设施（docker compose up -d）"
    Push-Location $repoRoot
    try {
        # PS 5.1：原生命令 stderr 会在 EAP=Stop 下中断脚本，这里局部降级并把输出写入日志
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $dockerLog = Join-Path $logDir "docker.log"
        & docker compose up -d 2>&1 | Out-File -FilePath $dockerLog -Encoding UTF8
        $composeExit = $LASTEXITCODE
        $ErrorActionPreference = $prevEap
        Get-Content $dockerLog -Tail 5 | ForEach-Object { Write-Host "  $_" }
        if ($composeExit -ne 0) { Write-Fail "docker compose 启动失败（详见 logs\docker.log）"; $failures++ }
    } finally { Pop-Location }
    $infraOk = $true
    foreach ($pair in @(@("postgres", $Script:Defaults.PostgresPort), @("meilisearch", $Script:Defaults.MeiliPort), @("redis", $Script:Defaults.RedisPort))) {
        $deadline = (Get-Date).AddSeconds(90)
        $ready = $false
        while ((Get-Date) -lt $deadline) {
            if (Test-PortListening $pair[1]) { $ready = $true; break }
            Start-Sleep -Milliseconds 1000
        }
        if ($ready) { Write-Ok "$($pair[0]) 就绪（端口 $($pair[1])）" }
        else { Write-Fail "$($pair[0]) 未在 90s 内就绪（端口 $($pair[1])）"; $infraOk = $false; $failures++ }
    }
}

# ---- 3. API ----
Write-Step "启动 api (FastAPI)"
Clear-OurPort $apiPort
$apiProcId = Read-ProcId "api"
if ($null -ne $apiProcId -and (Test-ProcAlive $apiProcId)) {
    Write-Ok "api 已在运行（pid $apiProcId），跳过"
} else {
    Remove-ProcIdFile "api"
    $env:GETOFFER_MEILISEARCH_URL = "http://127.0.0.1:$($Script:Defaults.MeiliPort)"
    $env:GETOFFER_REDIS_URL = "redis://localhost:$($Script:Defaults.RedisPort)/0"
    $proc = Start-Process -FilePath $apiVenvPython `
        -ArgumentList "-m", "uvicorn", "getoffer.api.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "$apiPort" `
        -WorkingDirectory (Join-Path $repoRoot "apps\api") `
        -RedirectStandardOutput (Join-Path $logDir "api.out.log") `
        -RedirectStandardError (Join-Path $logDir "api.err.log") `
        -WindowStyle Hidden -PassThru
    Save-ProcId "api" $proc.Id
    if (Wait-HttpOk "http://127.0.0.1:$apiPort/api/health" 90) { Write-Ok "api 健康（pid $($proc.Id)，端口 $apiPort）" }
    else {
        Write-Fail "api 健康检查未通过，日志尾部："
        Get-Content (Join-Path $logDir "api.err.log") -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
        $failures++
    }
}

# ---- 4. Agents ----
Write-Step "启动 agents (pi 运行时)"
Clear-OurPort $agentsPort
$agentsProcId = Read-ProcId "agents"
if ($null -ne $agentsProcId -and (Test-ProcAlive $agentsProcId)) {
    Write-Ok "agents 已在运行（pid $agentsProcId），跳过"
} else {
    Remove-ProcIdFile "agents"
    $env:AGENT_PORT = "$agentsPort"
    $env:AGENT_DATA_DIR = "../../data/sessions"
    $env:API_BASE_URL = "http://127.0.0.1:$apiPort"
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm run dev" `
        -WorkingDirectory (Join-Path $repoRoot "apps\agents") `
        -RedirectStandardOutput (Join-Path $logDir "agents.out.log") `
        -RedirectStandardError (Join-Path $logDir "agents.err.log") `
        -WindowStyle Hidden -PassThru
    Save-ProcId "agents" $proc.Id
    if (Wait-HttpOk "http://127.0.0.1:$agentsPort/health" 60) { Write-Ok "agents 健康（pid $($proc.Id)，端口 $agentsPort）" }
    else {
        Write-Fail "agents 健康检查未通过，日志尾部："
        Get-Content (Join-Path $logDir "agents.err.log") -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
        $failures++
    }
}

# ---- 5. Web ----
Write-Step "启动 web (Next.js)"
Clear-OurPort $webPort
$envLocal = Join-Path $repoRoot "apps\web\.env.local"
@"
API_PROXY_TARGET=http://127.0.0.1:$apiPort
AGENTS_PROXY_TARGET=http://127.0.0.1:$agentsPort
"@ | Set-Content -Path $envLocal -Encoding UTF8
Write-Ok "已写 apps\web\.env.local（同源代理指向本次解析的 api/agents 端口）"

if (-not $Dev) {
    # 生产模式：无构建产物时先构建（路由预编译，页面切换不卡；见 search/前端性能优化调研.md）
    $buildId = Join-Path $repoRoot "apps\web\.next\BUILD_ID"
    if (-not (Test-Path $buildId)) {
        Write-Step "生产构建（首次约 1-3 分钟，日志 logs\web-build.log）"
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        Push-Location (Join-Path $repoRoot "apps\web")
        try {
            cmd /c "npm run build" *> (Join-Path $logDir "web-build.log")
            $buildExit = $LASTEXITCODE
            $ErrorActionPreference = $prevEap
            if ($buildExit -ne 0) {
                Write-Fail "next build 失败（详见 logs\web-build.log）"
                Get-Content (Join-Path $logDir "web-build.log") -Tail 10 | ForEach-Object { Write-Host "    $_" }
                $failures++
            } else { Write-Ok "构建完成" }
        } finally { Pop-Location }
    } else { Write-Ok "已有构建产物，跳过 build（改动代码后删除 apps\web\.next 可强制重建）" }
}

$webProcId = Read-ProcId "web"
if ($null -ne $webProcId -and (Test-ProcAlive $webProcId)) {
    Write-Ok "web 已在运行（pid $webProcId），跳过（如需新端口请先 stop）"
} else {
    Remove-ProcIdFile "web"
    $webCmd = if ($Dev) { "npm run dev -- -p $webPort" } else { "npm run start -- -p $webPort" }
    $modeText = if ($Dev) { "dev" } else { "production" }
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", $webCmd `
        -WorkingDirectory (Join-Path $repoRoot "apps\web") `
        -RedirectStandardOutput (Join-Path $logDir "web.out.log") `
        -RedirectStandardError (Join-Path $logDir "web.err.log") `
        -WindowStyle Hidden -PassThru
    Save-ProcId "web" $proc.Id
    if (Wait-HttpOk "http://127.0.0.1:$webPort" 180) { Write-Ok "web 就绪（$modeText，pid $($proc.Id)，端口 $webPort）" }
    else {
        Write-Fail "web 健康检查未通过，日志尾部："
        Get-Content (Join-Path $logDir "web.err.log") -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
        $failures++
    }
}

# ---- 6. 密钥提醒 ----
Write-Step "密钥检查"
$apiKey = Get-DotEnvValue (Join-Path $repoRoot "apps\api\.env") "GETOFFER_LLM__API_KEY"
$agentsKey = Get-DotEnvValue (Join-Path $repoRoot "apps\agents\.env") "DEEPSEEK_API_KEY"
if ([string]::IsNullOrEmpty($apiKey)) {
    Write-Warn2 "apps\api\.env 的 GETOFFER_LLM__API_KEY 未填写：LLM 相关功能将显式报 503（其余可用）"
}
if ([string]::IsNullOrEmpty($agentsKey)) {
    Write-Warn2 "apps\agents\.env 的 DEEPSEEK_API_KEY 未填写：模拟面试将显式报 503（服务本身可用）"
}
if (-not [string]::IsNullOrEmpty($apiKey) -and -not [string]::IsNullOrEmpty($agentsKey)) {
    Write-Ok "两个密钥均已配置"
}

# ---- 7. 汇总 ----
Write-Host ""
Write-Host "=== 启动完成 ===" -ForegroundColor White
Write-Host ("  web    : http://127.0.0.1:{0}" -f $webPort)
Write-Host ("  api    : http://127.0.0.1:{0}/api/health" -f $apiPort)
Write-Host ("  agents : http://127.0.0.1:{0}/health" -f $agentsPort)
Write-Host ("  日志目录: {0}   停止: stop.bat" -f $logDir)
if ($failures -gt 0) { Write-Host "  有 $failures 项未通过健康检查，请看上方日志" -ForegroundColor Yellow; exit 1 }
