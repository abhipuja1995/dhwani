#!/bin/bash
# ─────────────────────────────────────────────────────────────────
#  Dhwani Dialer — local dev starter (no Docker required)
#
#  Starts:
#    :3000  →  Agent UI  (static HTML, Python http.server)
#    :8000  →  API       (FastAPI + SQLite, uvicorn)
#
#  Usage:
#    chmod +x run_local.sh
#    ./run_local.sh
# ─────────────────────────────────────────────────────────────────

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── colours ──────────────────────────────────────────────────────
GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'

echo ""
echo -e "${BOLD}${BLUE}  Dhwani — Collections Intelligence${NC}"
echo -e "  ${YELLOW}Local dev mode (SQLite · no Docker required)${NC}"
echo ""

# ── kill any previous instances ───────────────────────────────────
echo -e "  Cleaning up old processes…"
pkill -f "http.server 3000" 2>/dev/null || true
pkill -f "uvicorn dialer" 2>/dev/null || true
sleep 0.5

# ── start UI (static files) ───────────────────────────────────────
UI_DIR="$SCRIPT_DIR/ui"
echo -e "  ${GREEN}►${NC} Starting UI on ${BOLD}http://localhost:3000${NC}"
python3 -m http.server 3000 --directory "$UI_DIR" \
  > /tmp/dialer_ui.log 2>&1 &
UI_PID=$!

# ── start API (FastAPI + SQLite) ──────────────────────────────────
API_DIR="$SCRIPT_DIR/api"
echo -e "  ${GREEN}►${NC} Starting API on ${BOLD}http://localhost:8000${NC}"
cd "$API_DIR"
LOCAL=1 python3 -m uvicorn dialer.main_local:app \
  --host 0.0.0.0 --port 8000 \
  > /tmp/dialer_api.log 2>&1 &
API_PID=$!

# ── wait for API to be ready ──────────────────────────────────────
echo -n "  Waiting for API"
for i in $(seq 1 20); do
  sleep 0.5
  if curl -s http://localhost:8000/health >/dev/null 2>&1; then
    echo -e " ${GREEN}ready${NC}"
    break
  fi
  echo -n "."
done

echo ""
echo -e "  ┌──────────────────────────────────────────┐"
echo -e "  │  ${BOLD}Agent UI${NC}   →  http://localhost:3000      │"
echo -e "  │  ${BOLD}API docs${NC}   →  http://localhost:8000/docs  │"
echo -e "  │  ${BOLD}Health${NC}     →  http://localhost:8000/health │"
echo -e "  └──────────────────────────────────────────┘"
echo ""
echo -e "  Logs:  /tmp/dialer_ui.log   /tmp/dialer_api.log"
echo -e "  ${YELLOW}Press Ctrl+C to stop both servers${NC}"
echo ""

# ── open browser ──────────────────────────────────────────────────
if command -v open >/dev/null 2>&1; then
  sleep 0.5
  open http://localhost:3000
fi

# ── wait for Ctrl+C ───────────────────────────────────────────────
trap "echo ''; echo 'Stopping…'; kill $UI_PID $API_PID 2>/dev/null; exit 0" INT TERM
wait
