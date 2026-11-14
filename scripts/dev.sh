#!/usr/bin/env bash
# Start API (:8000) and web UI (:3000) for local use. Requires a reachable Postgres (see README) or FS_DATABASE_URL=sqlite:///./dev.db
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# start a local PostgreSQL if one is installed as a service and not running (no-op otherwise)
(pg_isready -q 2>/dev/null || service postgresql start >/dev/null 2>&1 || true); sleep 2
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true; pkill -f ".next/standalone/server.js" 2>/dev/null || true
sleep 1
(cd "$ROOT/backend" && nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 > "$ROOT/data/api.log" 2>&1 &)
cd "$ROOT/frontend"
[ -d .next/standalone ] || npm run build
rm -rf .next/standalone/.next/static && cp -r .next/static .next/standalone/.next/static
(PORT=3000 HOSTNAME=0.0.0.0 nohup node .next/standalone/server.js > "$ROOT/data/web.log" 2>&1 &)
for i in $(seq 1 40); do curl -fsS localhost:8000/api/health >/dev/null 2>&1 && break; sleep 1; done
echo "API  http://localhost:8000/docs"; echo "UI   http://localhost:3000"
