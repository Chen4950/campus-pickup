param(
    [switch]$Install,
    [ValidateRange(1, 65535)][int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Install) {
        if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
            python -m venv .venv
            if ($LASTEXITCODE) { throw '创建 Python 环境失败。' }
        }
        & '.venv/Scripts/python.exe' -m pip install -r requirements.txt
        if ($LASTEXITCODE) { throw '安装 Python 依赖失败。' }
        npm.cmd ci
        if ($LASTEXITCODE) { throw '安装前端依赖失败。' }
    }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe') -or -not (Test-Path -LiteralPath 'node_modules')) {
        throw '请先用 .\start.ps1 -Install 安装项目依赖。'
    }
    npm.cmd run build
    if ($LASTEXITCODE) { throw '前端构建失败。' }
    & '.venv/Scripts/python.exe' -m uvicorn backend.app:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
