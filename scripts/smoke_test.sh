#!/usr/bin/env bash
# End-to-end smoke test against a running stack.
# Assumes `docker compose up -d` is running in /docker/espresso-club.

set -euo pipefail

APP="${APP:-http://localhost:8080}"
NFC="${NFC:-http://localhost:9999}"
LNBITS="${LNBITS:-http://localhost:5000}"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }

step() { printf "\033[36m▶ %s\033[0m\n" "$*"; }

step "checking app health"
curl -fsSL "$APP/healthz" | grep -q '"ok": *true' && green "  app OK"

step "checking lnbits health"
curl -fsSL "$LNBITS/api/v1/health" >/dev/null && green "  lnbits OK"

step "checking nfc simulator"
curl -fsSL -X POST "$NFC/tap" -H 'Content-Type: application/json' \
    -d '{"uid":"SMOKE-TEST-CARD"}' >/dev/null && green "  simulator OK"

step "querying app state"
curl -fsSL "$APP/api/state" | tee /dev/stderr | grep -q '"session"'

green "✅ smoke test passed"
