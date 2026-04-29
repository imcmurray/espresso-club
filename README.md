# Office Espresso Club

Lightning-powered, fair, prepaid coffee accounting for a privately-owned office espresso machine.

See [`espresso-club.md`](./espresso-club.md) for the full design spec.

## What's in here

```
bitcoin-idea/
├── espresso-club.md         # Full design spec
├── README.md                # this file
├── app/                     # FastAPI/HTMX espresso webapp
│   ├── main.py
│   ├── db.py                # SQLite users + ledger
│   ├── lnbits_client.py     # LNbits REST client
│   ├── relay.py             # Shelly + simulator drivers
│   ├── routers/             # /onboard, /menu, /buy, /topup, /admin
│   ├── templates/           # Jinja2/HTMX
│   └── static/              # CSS, JS
├── nfc_daemon/              # PN532 reader (real + simulator)
├── slack_bot/               # Onboarding + low-balance pings + leaderboard
├── scripts/
│   ├── make_sign.py         # Phase 0 printable QR sign generator
│   ├── smoke_test.sh        # End-to-end smoke test
│   └── seed_demo_users.py   # Insert a few users for quick demos
├── signs/                   # Output directory for printable signs
└── tests/                   # pytest

../docker/espresso-club/
└── docker-compose.yml       # LNbits + Phoenixd + app stack
```

## Quick start (development)

```bash
# 1. Bring up the Lightning + app stack (FakeWallet, no real LN traffic)
cd /docker/espresso-club
docker compose up -d

# 2. Seed a few demo users
python3 /project/bitcoin-idea/scripts/seed_demo_users.py

# 3. Visit:
#   http://localhost:8080/menu        — touchscreen UI
#   http://localhost:8080/admin       — operator dashboard
#   http://localhost:5000             — LNbits admin

# 4. Simulate an NFC tap (no hardware needed):
curl -X POST http://localhost:8080/api/nfc/tap -d '{"uid":"DEMO-SARAH"}' \
     -H 'Content-Type: application/json'
```

## Switching to real Lightning (Phoenixd)

See [`docs/phoenixd.md`](./docs/phoenixd.md) for the full procedure.
TL;DR: `docker compose --profile phoenixd up -d`, copy the API key, update LNbits funding source.

## Hardware deployment (Raspberry Pi)

See [`docs/hardware.md`](./docs/hardware.md).

## Phases

- **Phase 0** — `scripts/make_sign.py` produces a printable QR sign. Tape it up. No tech needed.
- **Phase 1** — `docker compose up`. Full software MVP, simulators stand in for hardware.
- **Phase 2** — Real PN532 + Shelly relay on a Pi. Flip `TAP_SIMULATOR=false` and `RELAY_DRIVER=shelly`.
- **Phase 3–4** — Soft launch with coworkers, then office-wide. Operational, not code.
- **Phase 5** — Slack bot, leaderboard, e-ink display niceties. Most are already in here.

## Documentation

- [`docs/phoenixd.md`](./docs/phoenixd.md) — switching from FakeWallet to real Lightning
- [`docs/hardware.md`](./docs/hardware.md) — Pi assembly, wiring, kiosk setup
- [`docs/operations.md`](./docs/operations.md) — onboarding, topping up, refilling, auditing

## Tests

```bash
cd /project/bitcoin-idea
python3 -m pytest tests/    # unit tests (fast, hermetic)
./scripts/smoke_test.sh     # end-to-end against running stack
```

## Known issues

- **Building Docker images inside an LXC with broken apparmor**: if `docker
  compose build` fails with `apparmor_parser: Access denied`, that's an
  LXC-host config issue, not a project bug. Fix on the host: add `"apparmor":
  false` to `/etc/docker/daemon.json` and restart Docker, or build on a
  non-LXC machine and push the image. Real Raspberry Pi OS deployments don't
  hit this.
