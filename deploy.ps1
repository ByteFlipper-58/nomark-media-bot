#Requires -Version 5.1
<#
.SYNOPSIS
    Interactive setup and deployment of the NoMark Telegram bot onto Modal Serverless.
#>

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== NoMark Telegram Bot -> Modal Serverless Deploy ===" -ForegroundColor Cyan

# 1. Check Modal CLI
if (-not (Get-Command modal -ErrorAction SilentlyContinue)) {
    Write-Host "Modal CLI not found. Installing via uv..." -ForegroundColor Yellow
    uv tool install --python 3.12 modal
}

# 2. Check Modal auth
$modalConfig = Join-Path $HOME ".modal.toml"
if (-not (Test-Path $modalConfig)) {
    Write-Host "`nOpening browser to log in to Modal (Starter plan = `$0/mo idle + `$30/mo free credits)." -ForegroundColor Yellow
    modal setup
}

# 3. Collect bot credentials
$botToken = (Read-Host "`nPaste TELEGRAM_BOT_TOKEN from @BotFather").Trim()
if (-not $botToken) {
    throw "TELEGRAM_BOT_TOKEN cannot be empty."
}

Write-Host "`nIMPORTANT: Strongly recommended to enter your Telegram User ID(s) (via @userinfobot)" -ForegroundColor Yellow
Write-Host "so strangers who find your bot cannot spend your Modal GPU credits." -ForegroundColor Yellow
$allowedUsers = (Read-Host "Allowed Telegram User IDs (comma-separated, or Enter for open access)").Trim()
$hfToken = (Read-Host "Hugging Face token (optional, press Enter to skip)").Trim()

# Generate random 64-char hex secret for webhook verification
$rngBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($rngBytes)
$webhookSecret = ([System.BitConverter]::ToString($rngBytes) -replace "-", "").ToLowerInvariant()

$appName = if ($env:NOMARK_APP_NAME) { $env:NOMARK_APP_NAME } else { "raiw-telegram-bot" }
$secretName = if ($env:NOMARK_SECRET_NAME) { $env:NOMARK_SECRET_NAME } else { "raiw-bot-secrets" }

# 4. Save secrets to Modal
Write-Host "`nSaving Modal secret ($secretName)..." -ForegroundColor Cyan
$secretArgs = @(
    "secret", "create", "--force", $secretName,
    "TELEGRAM_BOT_TOKEN=$botToken",
    "TELEGRAM_WEBHOOK_SECRET=$webhookSecret",
    "ALLOWED_USER_IDS=$allowedUsers",
    "HF_TOKEN=$hfToken"
)
& modal @secretArgs
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create Modal secret."
}

# 5. Deploy Modal app
Write-Host "`nBuilding images & deploying modal_app.py (first build takes 2-4 min)..." -ForegroundColor Cyan
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
& modal deploy modal_app.py 2>&1 | Tee-Object -Variable deployOutput
if ($LASTEXITCODE -ne 0) {
    throw "Modal deploy failed."
}

# 6. Resolve webhook URL (supports regional URLs like *.us-east.modal.run)
$webhookUrl = $null
foreach ($line in $deployOutput) {
    $text = $line.ToString()
    if ($text -match "(https://[a-zA-Z0-9._-]+--[a-zA-Z0-9._-]+telegram-webhook(?:\.[a-z0-9-]+)?\.modal\.run)") {
        $webhookUrl = $Matches[1]
        break
    }
}

if (-not $webhookUrl) {
    $modalPython = Join-Path $env:APPDATA "uv\tools\modal\Scripts\python.exe"
    if (Test-Path $modalPython) {
        $webhookUrl = (& $modalPython -c "import modal; print(modal.Function.from_name('$appName', 'telegram_webhook').get_web_url())").Trim()
    }
}

if (-not $webhookUrl) {
    Write-Host "`nCould not auto-detect webhook URL from Modal output." -ForegroundColor Yellow
    $webhookUrl = (Read-Host "Paste the telegram_webhook URL (*.modal.run) from the output above").Trim()
}

Write-Host "`nWebhook URL: $webhookUrl" -ForegroundColor Green

# 7. Register Telegram webhook & slash commands
Write-Host "Registering webhook & commands with Telegram..." -ForegroundColor Cyan
$setWebhookBody = @{
    url                  = $webhookUrl
    secret_token         = $webhookSecret
    drop_pending_updates = $true
    allowed_updates      = @("message", "callback_query")
} | ConvertTo-Json

$resp = Invoke-RestMethod `
    -Uri "https://api.telegram.org/bot$botToken/setWebhook" `
    -Method Post `
    -ContentType "application/json" `
    -Body $setWebhookBody

if (-not $resp.ok) {
    throw "Telegram setWebhook failed: $($resp | ConvertTo-Json -Compress)"
}

$commandsBody = @{
    commands = @(
        @{ command = "start"; description = "Main menu & mode selection" },
        @{ command = "settings"; description = "Settings (language, strength, EXIF, source)" },
        @{ command = "stats"; description = "Usage stats & Modal budget guard" },
        @{ command = "text"; description = "Clean hidden Unicode / C2PA from text" },
        @{ command = "help"; description = "Show help & modes" }
    )
} | ConvertTo-Json -Depth 3

Invoke-RestMethod `
    -Uri "https://api.telegram.org/bot$botToken/setMyCommands" `
    -Method Post `
    -ContentType "application/json" `
    -Body $commandsBody | Out-Null

Write-Host "`nDONE! NoMark is live on Modal." -ForegroundColor Green
Write-Host "Open your bot in Telegram and send /start to pick your language (EN / RU)." -ForegroundColor Cyan
Write-Host "Logs: modal app logs $appName --timestamps --tail 80" -ForegroundColor DarkGray
