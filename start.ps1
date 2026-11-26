param(
    [switch]$Install,
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$Lan,
    [string]$Certificate,
    [string]$PrivateKey
)

$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Install) {
        if (-not (Test-Path -LiteralPath '.venv/Scripts/pip.exe')) {
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
    if ([bool]$Certificate -ne [bool]$PrivateKey) {
        throw '请同时提供 HTTPS 证书和私钥。'
    }
    $bindAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
    $serverArgs = @('backend.app:app', '--host', $bindAddress, '--port', $Port)
    if ($Certificate) {
        $serverArgs += @('--ssl-certfile', $Certificate, '--ssl-keyfile', $PrivateKey)
    }
    & '.venv/Scripts/python.exe' -m uvicorn @serverArgs
} finally {
    Pop-Location
}
