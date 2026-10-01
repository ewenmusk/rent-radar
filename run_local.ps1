# 備援：在自己電腦上跑一次抓取並推上 GitHub（591 擋機房 IP 時用）
# 用法：在專案目錄執行  .\run_local.ps1
# 可在專案目錄放 .env 檔設定 NTFY_TOPIC、FB_MAIL_USER、FB_MAIL_PASS、SITE_URL（每行 KEY=VALUE）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2].Trim('"'), "Process")
        }
    }
}

git pull --rebase
python -m scraper.run
git add data
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m ("data: local " + (Get-Date -Format "yyyy-MM-ddTHH:mm"))
    git push
    Write-Host "已推上 GitHub，Pages 會在一兩分鐘內更新。"
} else {
    Write-Host "沒有新資料。"
}
