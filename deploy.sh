#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== NoMark Telegram Bot -> Modal Serverless Deploy ==="

# 1. Check Modal CLI
if ! command -v modal >/dev/null 2>&1; then
  echo "Modal CLI not found. Installing via uv or pip..."
  if command -v uv >/dev/null 2>&1; then
    uv tool install --python 3.12 modal
  else
    python3 -m pip install --user modal
  fi
fi

# 2. Check Modal authentication
if [ ! -f "$HOME/.modal.toml" ]; then
  echo ""
  echo "Opening browser to log in to Modal (Starter plan: \$0/mo idle + \$30/mo free credits)..."
  modal setup
fi

# 3. Collect bot credentials
echo ""
read -r -p "Paste TELEGRAM_BOT_TOKEN from @BotFather: " BOT_TOKEN
BOT_TOKEN="$(printf '%s' "$BOT_TOKEN" | tr -d '\r\n ')"
if [ -z "$BOT_TOKEN" ]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN cannot be empty." >&2
  exit 1
fi

echo ""
echo "IMPORTANT: Strongly recommended to restrict access to your own Telegram User ID(s)"
echo "(get yours via @userinfobot), otherwise anyone who finds your bot can spend your Modal GPU credits."
read -r -p "Allowed Telegram User IDs (comma-separated, or Enter for open access): " ALLOWED_USERS
read -r -p "Hugging Face token (optional, press Enter to skip): " HF_TOKEN

# Generate random 64-char hex webhook secret
WEBHOOK_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

APP_NAME="${NOMARK_APP_NAME:-raiw-telegram-bot}"
SECRET_NAME="${NOMARK_SECRET_NAME:-raiw-bot-secrets}"

# 4. Save secrets to Modal
echo ""
echo "Saving Modal secret ($SECRET_NAME)..."
modal secret create --force "$SECRET_NAME" \
  "TELEGRAM_BOT_TOKEN=$BOT_TOKEN" \
  "TELEGRAM_WEBHOOK_SECRET=$WEBHOOK_SECRET" \
  "ALLOWED_USER_IDS=$ALLOWED_USERS" \
  "HF_TOKEN=$HF_TOKEN"

# 5. Deploy Modal app
echo ""
echo "Building container images & deploying modal_app.py (first build takes 2-4 min)..."
DEPLOY_OUT="$(modal deploy modal_app.py 2>&1 | tee /dev/stderr)"

# 6. Resolve webhook URL
WEBHOOK_URL="$(printf '%s\n' "$DEPLOY_OUT" | grep -Eo 'https://[a-zA-Z0-9._-]+--[a-zA-Z0-9._-]+telegram-webhook(\.[a-z0-9-]+)?\.modal\.run' | head -n 1 || true)"
if [ -z "$WEBHOOK_URL" ]; then
  WEBHOOK_URL="$(python3 -c "import modal; print(modal.Function.from_name('$APP_NAME', 'telegram_webhook').get_web_url())" 2>/dev/null || true)"
fi
if [ -z "$WEBHOOK_URL" ]; then
  read -r -p "Paste the telegram_webhook URL (*.modal.run) from the output above: " WEBHOOK_URL
fi

echo ""
echo "Webhook URL: $WEBHOOK_URL"

# 7. Register Telegram webhook & bot commands
echo "Registering webhook & slash commands with Telegram..."
curl -fsS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"${WEBHOOK_URL}\",\"secret_token\":\"${WEBHOOK_SECRET}\",\"drop_pending_updates\":true,\"allowed_updates\":[\"message\",\"callback_query\"]}" \
  >/dev/null

curl -fsS -X POST "https://api.telegram.org/bot${BOT_TOKEN}/setMyCommands" \
  -H "Content-Type: application/json" \
  -d '{"commands":[{"command":"start","description":"Main menu & mode selection"},{"command":"settings","description":"Settings (language, strength, EXIF, source)"},{"command":"stats","description":"Usage stats & Modal budget guard"},{"command":"text","description":"Clean hidden Unicode / C2PA from text"},{"command":"help","description":"Show help & modes"}]}' \
  >/dev/null

echo ""
echo "DONE! NoMark is live on Modal."
echo "Open your bot in Telegram and send /start to choose your language."
echo "View logs anytime: modal app logs $APP_NAME --timestamps --tail 80"
