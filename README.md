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

## Quick start

### Use prebuilt images (recommended — and the only path on environments where local builds fail, like AppArmor-restricted LXCs)

Multi-arch images for `amd64` and `arm64` are published to GHCR by the
`build-and-push` workflow on every push to `main`. The Pi deployment
(`docs/hardware.md`) targets arm64; LXCs and dev laptops target amd64.

```bash
git clone https://github.com/imcmurray/espresso-club.git
cd espresso-club
cp .env.example .env

# Pull first, then run. The pull step is explicit so we never silently fall
# back to a local build (which is the failure mode on AppArmor-restricted LXCs).
docker compose pull
docker compose up -d

# Seed demo users (optional)
python3 scripts/seed_demo_users.py
```

Pin a specific build for production by setting `ESPRESSO_TAG=<git-sha>` in
`.env` instead of the default `latest`.

### Build locally (dev environments where AppArmor doesn't get in the way)

```bash
docker compose up -d --build
```

### Verify the stack

```
http://localhost:8080/menu    — touchscreen UI
http://localhost:8080/admin   — operator dashboard
http://localhost:5000         — LNbits admin

# Simulate an NFC tap (no hardware needed)
curl -X POST http://localhost:9999/tap \
     -H 'Content-Type: application/json' \
     -d '{"uid":"DEMO-SARAH"}'
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

## First-time setup after enabling the workflow

GHCR creates each new package as **private** by default, even when the source
repo is public. After the first successful run of `build-and-push`, flip
visibility to public for each of the three images so anyone can `docker pull`:

1. Visit https://github.com/imcmurray?tab=packages
2. For each of `espresso-club/app`, `espresso-club/nfc`, `espresso-club/slack`:
   - Click the package → **Package settings** → **Change visibility** → **Public**
3. (Once per package, lifetime of the project.)

## Documentation

- [`deploy/dockge/`](./deploy/dockge/) — drop-in [Dockge](https://github.com/louislam/dockge) stack file
- [`docs/release-pipeline.md`](./docs/release-pipeline.md) — push → GHA → GHCR → LXC pull-and-run loop, plus the monthly LNbits-unpin routine. **Start here if you're returning to the project after a break.**
- [`docs/phoenixd.md`](./docs/phoenixd.md) — switching from FakeWallet to real Lightning
- [`docs/hardware.md`](./docs/hardware.md) — Pi assembly, wiring, kiosk setup
- [`docs/operations.md`](./docs/operations.md) — onboarding, topping up, refilling, auditing

## Tests

```bash
cd /project/bitcoin-idea
python3 -m pytest tests/    # unit tests (fast, hermetic)
./scripts/smoke_test.sh     # end-to-end against running stack
```

## Pinned dependencies & known upstream quirks

- **LNbits**: pinned to `lnbits-legend:0.10.10`. Newer images (`lnbits:latest`,
  `lnbits-legend:0.11.x`) have a migration bug where the startup code runs
  `SELECT * FROM information_schema.tables` (PostgreSQL syntax) regardless of
  the actual database backend, so SQLite deployments crash on first boot.
  0.10.10 works as long as `LNBITS_DATABASE_URL` is left unset and LNbits
  picks the default SQLite path under `LNBITS_DATA_FOLDER`. Setting an
  explicit `sqlite://` URL re-triggers the bug.

- **LNbits User Manager extension**: auto-installed on first boot via
  `LNBITS_EXTENSIONS_MANIFESTS` + `LNBITS_EXTENSIONS_DEFAULT_INSTALL=usermanager`.
  Required for the espresso app's onboarding flow (`/onboard` creates a
  sub-wallet per staff member via the User Manager API). Without this, every
  onboarding submission 404s on `/usermanager/api/v1/users`. If you're seeing
  that error on an existing deploy, either redeploy the stack so the env vars
  take effect, or open the LNbits admin UI → Manage Extensions → install
  User Manager manually as a one-time fix.

## Known issues

### Building Docker images inside an LXC with broken AppArmor

If `docker compose build` fails with one of:

```
apparmor_parser: Access denied. You need policy admin privileges to manage profiles.
```

```
runc run failed: ... unable to apply apparmor profile:
write fsmount:fscontext:proc/thread-self/attr/apparmor/exec: no such file or directory
```

…that's an LXC-host config issue, not a project bug. The kernel exposes
AppArmor as enabled but the LXC namespace doesn't have access to write the
required `/proc/<pid>/attr/apparmor/exec` interface, so every intermediate
build container fails to start.

**What does *not* fix it (don't bother trying):**
- Adding `"apparmor": false` to `/etc/docker/daemon.json` — that's not a valid
  daemon directive and Docker refuses to start.
- `DOCKER_BUILDKIT=0 docker compose build` — the legacy builder hits the same
  `apparmor_parser` error because the daemon, not the builder, is what tries
  to apply the profile.
- `docker buildx build --security-opt apparmor=unconfined` — runc still tries
  to write to the missing `/proc/.../attr/apparmor/` interface and fails.

**What actually fixes it (host-side, requires Proxmox/LXC config access):**
- Configure the LXC to either disable AppArmor entirely (`lxc.apparmor.profile = unconfined` plus passing through the apparmor securityfs), or grant the
  LXC the `lxc.cap.keep` / `mount` capabilities it needs to write to
  `/proc/.../attr/apparmor/`.
- Or, simplest: build images on a non-LXC machine and push them to a registry
  the LXC can pull from.

Container **runtime** works fine in this LXC because every service uses
`security_opt: [apparmor=unconfined]` — that flag bypasses the runtime
profile load. The problem is build-time only, where there's no equivalent
escape hatch.

Real Raspberry Pi OS / VM deployments don't encounter this at all; it is
specific to Proxmox-style LXC containers with restricted AppArmor access.
