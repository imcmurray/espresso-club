# Release pipeline & automation

How code reaches the espresso machine, and how the version pins maintain themselves.

> **Read this doc when**: you've come back to the project after a few weeks and need to remember how the moving parts fit together — or something in the chain broke and you need to know where to look.

---

## The closed loop, in one diagram

```
                            ┌─────────────────────────────┐
                            │  developer pushes to main   │
                            └──────────────┬──────────────┘
                                           │
                                           ▼
                ┌──────────────────────────────────────────┐
                │  GitHub Actions: build-and-push          │
                │  (.github/workflows/build-and-push.yml)  │
                │                                          │
                │  matrix: app · nfc · slack               │
                │  multi-arch: linux/amd64,linux/arm64     │
                │  cache: type=gha (per-image scope)       │
                └──────────────┬───────────────────────────┘
                               │ docker push
                               ▼
                ┌──────────────────────────────────────────┐
                │  ghcr.io/imcmurray/espresso-club/{app,   │
                │     nfc, slack}:latest                   │
                │     ...:<git-sha>                        │
                └──────────────┬───────────────────────────┘
                               │ docker compose pull
                               ▼
                ┌──────────────────────────────────────────┐
                │  Deployment target                       │
                │  (Proxmox LXC today, Raspberry Pi later) │
                │                                          │
                │  $ docker compose pull                   │
                │  $ docker compose up -d                  │
                └──────────────────────────────────────────┘

                               ╳   no manual build  ╳
                               ╳   anywhere on the   ╳
                               ╳   deployment side   ╳

                    ─────────────────────────────────────

                ┌──────────────────────────────────────────┐
                │  Monthly routine: "Unpin LNbits when     │
                │  upstream is fixed"                      │
                │  https://claude.ai/code/routines/        │
                │     trig_01TQN5FAuS8V6Zej7ftPgX7v        │
                │                                          │
                │  cron: 0 8 1 * * (UTC)                   │
                │       = 04:00 EDT / 03:00 EST            │
                └──────────────┬───────────────────────────┘
                               │ on each fire
                               ▼
                ┌──────────────────────────────────────────┐
                │  1. Already an open "LNbits bump" PR?    │
                │     yes → exit silently                  │
                │  2. Pin still in docker-compose.yml?     │
                │     no  → exit silently                  │
                │  3. Docker available in env?             │
                │     no  → exit silently                  │
                │  4. Pull lnbits-legend:latest, boot it,  │
                │     check logs for information_schema    │
                │     AND confirm /api/v1/health 2xx       │
                │  5. Both pass → open PR; else silent     │
                └──────────────┬───────────────────────────┘
                               │
                               ▼
                ┌──────────────────────────────────────────┐
                │  Human reviews the PR ◄─── only place    │
                │  Merge if the proof looks right          │   human attention
                │  → pin-exists gate trips on next run     │   is required
                │  → routine becomes a permanent no-op     │
                └──────────────────────────────────────────┘
```

---

## What each piece does

### 1. The build pipeline (`.github/workflows/build-and-push.yml`)

Triggers on push to `main` when paths under `app/`, `nfc_daemon/`, `slack_bot/`, or the workflow file itself change. Builds three images in parallel via a strategy matrix, pushes them to GHCR.

Key choices baked in:

| Choice | Why |
|---|---|
| Matrix over images | Independent caches; an `app` change doesn't invalidate `nfc` or `slack` |
| `paths:` filter | A README-only commit doesn't burn CI minutes |
| `cache-from/to: type=gha,scope=<image>` | First build is full; subsequent builds reuse layers, dropping minutes to seconds |
| `linux/amd64,linux/arm64` | amd64 for the LXC and dev laptops; arm64 for the Pi deployment |
| Tags `:latest` and `:<sha>` | `latest` for tracking main; `<sha>` for production pinning |
| `permissions: packages: write` | Minimal scope needed to push to GHCR |
| Trusted-input-only `${{ }}` expressions | Nothing user-controlled reaches a `run:` step |

### 2. The image registry (`ghcr.io/imcmurray/espresso-club/*`)

GHCR holds three packages, one per image:
- `ghcr.io/imcmurray/espresso-club/app`
- `ghcr.io/imcmurray/espresso-club/nfc`
- `ghcr.io/imcmurray/espresso-club/slack`

All public, anonymously pullable. (Note: GitHub creates GHCR packages as private by default for some accounts — if you fork this repo and the workflow's first run produces denied-on-pull errors, flip each package to Public via Package settings.)

### 3. The deployment side (LXC today, Pi tomorrow)

`docker-compose.yml` references the GHCR images via `image:` and keeps `build:` as a fallback for local dev:

```yaml
espresso-app:
  image: ghcr.io/imcmurray/espresso-club/app:${ESPRESSO_TAG:-latest}
  build:
    context: .
    dockerfile: app/Dockerfile
```

The deployment runs:

```bash
docker compose pull           # explicit — never silently fall back to a build
docker compose up -d
```

This works on:
- The Proxmox LXC (where local builds are blocked by AppArmor — see `README.md` "Known issues")
- A Raspberry Pi (where local builds *do* work, but pulling from GHCR is faster anyway)
- A dev laptop (same)

To pin production to a specific build, set `ESPRESSO_TAG=<git-sha>` in `.env` instead of `latest`.

### 4. The monthly maintenance routine

Currently the only piece of automation that's *aware* of an upstream issue. Lives at:

- **Routine ID**: `trig_01TQN5FAuS8V6Zej7ftPgX7v`
- **Manage**: https://claude.ai/code/routines/trig_01TQN5FAuS8V6Zej7ftPgX7v
- **Schedule**: `0 8 1 * *` (first of every month at 08:00 UTC)

Five gates, in order. Any gate failing means silent exit (no PR, no notification):

1. **Open-PR gate** — if a "LNbits bump" PR is already open, do nothing.
2. **Pin-exists gate** — if the pin has already been lifted (manually or by a prior PR merged), do nothing.
3. **Docker-available gate** — if the cloud env lacks Docker, do nothing.
4. **Negative check** — `docker compose logs lnbits | grep information_schema` must return *empty*.
5. **Positive check** — `curl http://localhost:5000/api/v1/health` must return 2xx.

Only if 4 *and* 5 both pass does the routine open a PR titled `deps: bump LNbits — :latest now boots on SQLite`. The PR body includes the variant that worked, the timestamp, and verbatim proof from the checks.

### 5. The human-attention point

You will get exactly one notification from this entire pipeline, and only when there's something genuinely worth your attention: **a PR appears on the espresso-club repo titled `deps: bump LNbits — :latest now boots on SQLite`**.

When that happens:

1. Open the PR. Read the body — it shows you exactly which LNbits variant was tested, what the negative-check output looked like (should be empty), and what the positive-check output looked like (should be a 2xx health response).
2. Skim the diff. It should be:
   - `docker-compose.yml` — image tag changes from `lnbits-legend:0.10.10` to `lnbits-legend:latest`, and possibly `LNBITS_DATABASE_URL` re-added.
   - `README.md` — the "Pinned dependencies & known upstream quirks" entry for LNbits is removed or simplified.
3. Optionally pull the branch locally and re-run `docker compose up -d lnbits` to reproduce the green check.
4. Merge.

After the merge, the next monthly run hits the pin-exists gate and exits silently. The routine becomes a permanent no-op. You do not need to disable it — it self-disables by virtue of having succeeded.

---

## Common operations

### Inspect the pipeline state

```bash
# Latest workflow runs
gh run list --repo imcmurray/espresso-club --limit 5

# Watch the in-flight build
gh run watch <run-id>

# Inspect a published image's manifest (e.g. confirm multi-arch)
docker manifest inspect ghcr.io/imcmurray/espresso-club/app:latest
```

### Force a routine run early

```
RemoteTrigger {action: "run", trigger_id: "trig_01TQN5FAuS8V6Zej7ftPgX7v"}
```

…or via the web UI at the Manage URL above. Useful if you suspect upstream just fixed the bug and don't want to wait for the 1st of next month.

### Disable the routine

Toggle `enabled: false` from the web UI. Don't forget to re-enable if the bug isn't actually fixed yet.

### Emergency rollback (image regression breaks the office)

If a new push to main produces a broken `:latest` image:

```bash
# Pin to the previous good build by SHA
echo "ESPRESSO_TAG=<previous-sha>" >> /docker/espresso-club/.env
docker compose pull
docker compose up -d
```

The old `:<sha>` tags don't expire, so this works as long as the SHA is reachable on GHCR.

### Update or refit the routine prompt

```
RemoteTrigger {action: "update", trigger_id: "trig_01TQN5FAuS8V6Zej7ftPgX7v",
               body: {... new job_config ...}}
```

Only update if you find the routine is making noise (false-positive PRs) or going silent when it shouldn't (false-negative). Tune the gates rather than disable.

---

## What this pipeline does *not* automate

Be aware:

- **No automated merge.** A green PR from the routine still requires you to merge manually. This is deliberate — version-pin lifts should be human decisions.
- **No staging environment.** Builds go straight from `main` to `:latest`. If you want to add staging, the cleanest pattern is: route `main` to `:next`, only `:latest` from a separate tag-protected workflow.
- **No rollback automation.** The `:<sha>` tags are kept forever, but actually rolling back is a manual `ESPRESSO_TAG=` change in `.env`.
- **No dependency monitoring beyond LNbits.** If `lnbitsdocker/lnbits-legend` is removed from Docker Hub, or Phoenixd has a similar regression, you'll find out the hard way. Worth adding similar one-off routines if any other dependency starts being load-bearing in a fragile way.

---

## File index

| What | Where |
|---|---|
| Build & push workflow | `.github/workflows/build-and-push.yml` |
| Compose file | `docker-compose.yml` (root) |
| The LNbits pin and its rationale | `README.md` "Pinned dependencies & known upstream quirks" |
| LXC AppArmor wall | `README.md` "Known issues" |
| Operations runbook | `docs/operations.md` |
| Hardware deployment | `docs/hardware.md` |
| Phoenixd migration | `docs/phoenixd.md` |
| This doc | `docs/release-pipeline.md` |

---

## TL;DR

- Push code → GHA builds & publishes → LXC pulls & runs. Zero human steps after the push.
- A monthly background routine watches for LNbits upstream to fix the SQLite bug. When it does, you get one PR. Merge it; the routine self-disables.
- The only human attention required by this whole system is reviewing that one PR, whenever it eventually shows up. Could be next month, could be next year.
