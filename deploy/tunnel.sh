#!/usr/bin/env bash
# Public HTTPS address for FreJun: a Cloudflare quick tunnel to the app's host port.
#
#   deploy/tunnel.sh          start the tunnel (or reuse the running one), set PUBLIC_URL in .env, restart the app
#   deploy/tunnel.sh stop     stop the tunnel
#
# A quick tunnel's address changes every time it starts, so run this again after a server restart; it updates
# PUBLIC_URL (https://<random>.trycloudflare.com + BASE_PATH) and restarts the app so new calls use it.
# Run from the repository root.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
LOG="$ROOT/var/cloudflared.log"
PID_FILE="$ROOT/var/cloudflared.pid"
COMPOSE=(docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ENV_FILE")

env_value() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

running() { [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

if [[ "${1:-}" == "stop" ]]; then
  if running; then kill "$(cat "$PID_FILE")" && echo "Tunnel stopped."; else echo "No tunnel running."; fi
  rm -f "$PID_FILE"
  exit 0
fi

# The host port the app is published on (the left side of "...:<host>:8083" in the compose file).
PORT="$("${COMPOSE[@]}" port app 8083 2>/dev/null | awk -F: '{print $NF}')"
[[ -n "$PORT" ]] || { echo "The app container is not running; start it first." >&2; exit 1; }
BASE_PATH="$(env_value BASE_PATH)"
BASE_PATH="/${BASE_PATH#/}"; BASE_PATH="${BASE_PATH%/}"; [[ "$BASE_PATH" == "/" ]] && BASE_PATH=""

mkdir -p "$ROOT/var"
if ! running; then
  : > "$LOG"
  nohup cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" >> "$LOG" 2>&1 &
  echo $! > "$PID_FILE"
  echo "Started cloudflared (pid $(cat "$PID_FILE")) for http://localhost:$PORT"
fi

URL=""
for _ in $(seq 1 30); do
  URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | tail -1 || true)"
  [[ -n "$URL" ]] && break
  sleep 1
done
[[ -n "$URL" ]] || { echo "No tunnel address after 30 s; see $LOG" >&2; exit 1; }

PUBLIC_URL="$URL$BASE_PATH"
if [[ "$(env_value PUBLIC_URL)" != "$PUBLIC_URL" ]]; then
  if grep -qE '^PUBLIC_URL=' "$ENV_FILE"; then
    sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=$PUBLIC_URL|" "$ENV_FILE"
  else
    echo "PUBLIC_URL=$PUBLIC_URL" >> "$ENV_FILE"
  fi
  echo "PUBLIC_URL set to $PUBLIC_URL; restarting the app"
  "${COMPOSE[@]}" up -d --no-deps app >/dev/null
else
  echo "PUBLIC_URL already $PUBLIC_URL"
fi

# Wait until the address answers (new tunnels take a few seconds to be reachable).
for _ in $(seq 1 30); do
  if curl -fs -o /dev/null --max-time 5 "$PUBLIC_URL/api/v1/health/ready"; then
    echo "Reachable: $PUBLIC_URL/"
    exit 0
  fi
  sleep 2
done
echo "Tunnel started but $PUBLIC_URL does not answer yet; see $LOG" >&2
exit 1
