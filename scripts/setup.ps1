# setup.ps1 — 一次性环境准备：工具链检查、虚拟环境、npm 依赖、.env 初始化（绝不覆盖已有 .env）

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$repoRoot = Get-RepoRoot
Write-Host "=== get_offer 环境准备 ===" -ForegroundColor White

Write-Step "工具链检查"
$missing = @()
foreach ($tool in @("git", "docker", "node", "npm", "uv")) {
    if (Test-CommandExists $tool) { Write-Ok "$tool" } else { $missing += $tool; Write-Fail "$tool 未找到" }
}
if ($missing.Count -gt 0) { Write-Fail "请先安装: $($missing -join ', ')"; exit 1 }

Write-Step "Python 虚拟环境（apps/api）"
$apiDir = Join-Path $repoRoot "apps\api"
$venvPython = Join-Path $apiDir ".venv\Scripts\python.exe"
Push-Location $apiDir
try {
    if (-not (Test-Path $venvPython)) {
        uv venv | ForEach-Object { Write-Host "  $_" }
    }
    Write-Host "  安装依赖（uv pip install -e .[dev]）…"
    uv pip install --python $venvPython -e ".[dev]" --quiet
    Write-Ok "api 依赖就绪"
} finally { Pop-Location }

foreach ($app in @("agents", "web")) {
    Write-Step "npm 依赖（apps/$app）"
    $appDir = Join-Path $repoRoot "apps\$app"
    if (Test-Path (Join-Path $appDir "node_modules")) {
        Write-Ok "node_modules 已存在，跳过"
    } else {
        Push-Location $appDir
        try {
            npm install --no-audit --no-fund 2>&1 | Select-Object -Last 2 | ForEach-Object { Write-Host "  $_" }
            if ($LASTEXITCODE -ne 0) { Write-Fail "npm install 失败"; exit 1 }
            Write-Ok "$app 依赖就绪"
        } finally { Pop-Location }
    }
}

Write-Step "初始化 .env（已有则不动）"
$pairs = @(
    @{ App = "api";    Example = ".env.example"; Target = ".env" },
    @{ App = "agents"; Example = ".env.example"; Target = ".env" }
)
foreach ($pair in $pairs) {
    $target = Join-Path $repoRoot "apps\$($pair.App)\$($pair.Target)"
    if (Test-Path $target) { Write-Ok "apps\$($pair.App)\$($pair.Target) 已存在，保留" }
    else {
        Copy-Item (Join-Path $repoRoot "apps\$($pair.App)\$($pair.Example)") $target
        Write-Ok "已创建 apps\$($pair.App)\$($pair.Target)"
    }
}

Write-Host ""
Write-Host "=== 环境就绪 ===" -ForegroundColor White
Write-Host "下一步："
Write-Host "  1. 编辑 apps\api\.env      填 GETOFFER_LLM__API_KEY"
Write-Host "  2. 编辑 apps\agents\.env   填 DEEPSEEK_API_KEY"
Write-Host "  3. 双击 start.bat 启动全部服务（status.bat 看状态，stop.bat 停止）"
