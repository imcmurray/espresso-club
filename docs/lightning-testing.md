# Lightning testing — switching from FakeWallet to real Phoenixd

This doc walks you through deploying the espresso-club stack with real Bitcoin Lightning, capturing the seed phrase safely, funding the node, and verifying every flow (onboard → topup → drink → gift).

> **Read the WHOLE thing once before you start.** The seed-capture step has a small window and can't be redone.

---

## What you'll have after this

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Phoenixd   │ ←→ │    LNbits    │ ←→ │ espresso-app │ ←→ │  Touchscreen │
│ (real BTC)   │    │ (sub-wallets)│    │ (UI + logic) │    │   browser    │
│ ACINQ LSP    │    │ v1.5.4       │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

- **Phoenixd** holds the real BTC and connects to ACINQ as your Lightning Service Provider (no Bitcoin Core, no node management — ACINQ auto-opens channels as needed).
- **LNbits** sits on top, giving each staff member a sub-wallet. Internal transfers between sub-wallets are free; only the perimeter (in/out) pays Lightning fees.
- The espresso-app onboards staff, handles topups and drinks, and bridges to LNbits via API.

---

## Pre-flight (do these BEFORE deploying)

### 1. Decide your max balance

What's the most money you're comfortable sitting in this stack at any time? For a typical office I'd cap it at $200 — sweep to your personal Lightning wallet whenever the operator wallet exceeds that.

### 2. Prepare an offline place to write the seed

Paper, metal seed plate, or a hardware wallet's already-existing seed page. **Not** a text file, **not** a password manager (recoverable — but cloud-synced, breach-prone).

You'll have to write down 12 words exactly once.

### 3. Have a personal Lightning wallet ready

You'll send a small inbound payment to bootstrap the first ACINQ channel. Any of these work:

- Wallet of Satoshi (mobile)
- Phoenix Wallet (mobile, by ACINQ — same company as phoenixd)
- Strike (US)
- Cash App (US)
- Alby (browser extension)

You only need ~$5–10 of sats in it.

---

## Deployment

In Dockge:

1. **espresso-club stack → Editor**
2. Re-paste the latest [compose.yaml](https://github.com/imcmurray/espresso-club/blob/main/deploy/dockge/compose.yaml) from the repo. (Or pull the diff manually: it adds a `phoenixd` service, a `lnbits-init` service, switches the lnbits image to `lnbits/lnbits:v1.5.4`, and adds an `LNBITS_BACKEND_WALLET_CLASS: PhoenixdWallet` env.)
3. **Save → Deploy**

This will:

- Pull all images
- Bring up Phoenixd
- Phoenixd generates a 12-word seed and writes it to `/phoenix/.phoenix/seed.dat` inside the container
- LNbits starts after Phoenixd is healthy, auto-discovers the API password
- `lnbits-init` runs the first-install wizard via API, saves admin credentials to `/lnbits-data/admin.json`
- espresso-app starts after lnbits-init exits cleanly

Wait until all containers show **Healthy** (or `Running` for `nfc-daemon` and `Exited` for `lnbits-init`). Should take ~1 minute.

---

## Step 1 — capture the seed phrase

This is the most important step. The seed is the only way to recover funds if Docker volumes are destroyed.

In Dockge → espresso-phoenixd container → **Terminal** (or via SSH on the host):

```bash
docker exec espresso-phoenixd cat /phoenix/.phoenix/seed.dat
```

You'll see 12 English words separated by spaces — that's your BIP39 seed phrase. **Write it down on paper, in order.**

Do not:
- Take a screenshot stored in a cloud-synced folder
- Paste it into a chat / email / GitHub issue
- Store it in a password manager you don't own (1Password fine; LastPass questionable; "free Notion" no)

Verify your handwriting by reading the words back from paper to the screen, in order.

Once you've written it down, save the LNbits admin credentials too (these are easier — they're already in a file):

```bash
docker exec espresso-lnbits cat /data/admin.json
```

Bookmark the username + password somewhere convenient. You'll use them if you ever want to log into the LNbits UI directly.

---

## Step 2 — sanity check (no real money yet)

Visit:

- `http://<dockge-host>:8080/menu` — touchscreen UI, should show "Tap your card to begin"
- `http://<dockge-host>:8080/admin` — admin dashboard, empty user list initially
- `http://<dockge-host>:5000` — LNbits UI, should show login (use admin credentials from above) — but you don't need to log in for normal operation

If the touchscreen UI loads, the espresso-app's auto-bootstrap successfully discovered the LNbits admin key and is ready to onboard staff.

---

## Step 3 — first onboard

This creates an LNbits sub-wallet for your test user but doesn't move any real money yet.

1. Visit `http://<dockge-host>:8080/onboard`
2. Enter a test name, e.g. `Test1`
3. Submit — you'll be redirected to `http://<dockge-host>:8080/topup/<id>`
4. The page shows: `Test1 · Balance: $0.00` and four topup buttons: $5 / $10 / $20 / $50

If you see a 500 error, something went wrong. Most likely: the espresso-app is still using a pre-Phoenixd image (it was pulled before today's update). Force-pull and restart:

```bash
docker compose pull espresso-app && docker compose up -d espresso-app
```

Then retry. If the error persists, check:

```bash
docker logs espresso-app | tail -20
docker exec espresso-app cat /lnbits-data/.super_user        # should print the SUPER_USER UUID
```

---

## Step 4 — first inbound payment (bootstraps Phoenixd channel)

This is where real money first enters the stack. Recommended first amount: **$5–10**.

> ⚠️ ACINQ charges a one-time channel-open fee on your first inbound payment. Roughly 1% of the amount with a minimum (~3,000 sats / ~$1.50). So a first $10 topup might land as ~$8.50 in your wallet. After this, subsequent inbound payments within the channel size are nearly free.

Steps:

1. On the topup page from Step 3, click **$10**
2. A QR code appears
3. Open your personal Lightning wallet (Wallet of Satoshi, Phoenix, etc.)
4. Scan the QR
5. Confirm the payment in your personal wallet
6. **Watch Phoenixd's logs while this happens**:

   ```bash
   docker logs -f espresso-phoenixd | grep -iE 'incoming|channel|opened'
   ```

   You should see something like `received incoming payment` and `channel opened`.

7. The espresso-app polls the invoice every 2s. Within a few seconds, the QR card on your browser should swap to **`✅ Paid! New balance: $8.50`** (or close to that — minus the channel-open fee).

If the QR sits there for >60 seconds without changing:

- Check the Phoenixd logs above for errors.
- Check that your personal wallet actually paid (some wallets fail silently if they can't find a route).
- The invoice may have expired (LNbits invoices expire after a few minutes). Click a topup button again to generate a new one.

---

## Step 5 — drink purchase (free internal transfer)

This exercises the LNbits-internal transfer path. **No real Lightning involvement** — just a database update inside LNbits.

1. Go back to `http://<dockge-host>:8080/menu`
2. Simulate an NFC tap (in lieu of having a real card):

   ```bash
   curl -X POST http://<dockge-host>:9999/tap -H 'Content-Type: application/json' -d '{"uid":"DEMO-CARD"}'
   ```

   First call registers the card to whoever was in the pending-onboard state. If `Test1` from Step 3 hadn't tapped yet, this assigns the card to them.

3. Tap a second time to start a fresh session.
4. The browser should refresh to `Hi Test1 · Balance: $8.50` (or whatever's left after fees).
5. Click any drink (e.g. `Single espresso $0.40`).
6. The screen returns to idle with: `☕ Enjoy your Single espresso, Test1! (-$0.40, balance $8.10)`

If this works: the internal-transfer path is solid. Drinks consume from the user's sub-wallet → operator's main wallet, free, no fees, no Lightning traffic.

---

## Step 6 — gift flow

1. Onboard a second test user: `http://<dockge-host>:8080/onboard` → `Test2`
2. Tap their card with a different UID to register:
   ```bash
   curl -X POST http://<dockge-host>:9999/tap -d '{"uid":"DEMO-CARD-2"}' -H 'Content-Type: application/json'
   ```
3. Now have Test1 gift Test2 a coffee:
   ```bash
   curl -X POST http://<dockge-host>:9999/tap -d '{"uid":"DEMO-CARD"}' -H 'Content-Type: application/json'
   ```
4. On the touchscreen browser → click **🎁 Gift a drink to a teammate** → click `Test2` → click `Latte`
5. Screen returns to idle with `🎁 You gifted Test2 a Latte!`
6. Tap Test2's card again:
   ```bash
   curl -X POST http://<dockge-host>:9999/tap -d '{"uid":"DEMO-CARD-2"}' -H 'Content-Type: application/json'
   ```
7. Test2's screen shows: `Hi Test2 · Balance: $1.10` and a banner `🎁 Test1 gifted you a Latte ($1.10) — already in your balance.`

Real money flowed: Test1's $1.10 → Test2's wallet, internal transfer, free.

---

## Step 7 — sweep (outbound to your personal wallet)

When the operator wallet (the one that drinks credit into) accumulates funds, you sweep them to your personal Lightning wallet to actually buy beans.

Manual sweep (until we add an admin button):

1. Get the operator wallet's keys. The operator wallet is the LNbits super-user's wallet (created during first-install). Its admin key is in:
   ```bash
   docker exec espresso-lnbits python3 -c "
   import sqlite3
   c = sqlite3.connect('/data/database.sqlite3')
   row = c.execute('SELECT id, name, adminkey, balance FROM wallets ORDER BY created_at LIMIT 1').fetchone()
   print(row)
   "
   ```
2. In your personal Lightning wallet, generate an invoice for the amount you want to sweep (e.g. $20).
3. Use LNbits's HTTP API to pay that invoice from the operator wallet:
   ```bash
   ADMINKEY=<from step 1>
   BOLT11=<the invoice from step 2>
   curl -X POST http://<dockge-host>:5000/api/v1/payments \
     -H "X-Api-Key: $ADMINKEY" \
     -H "Content-Type: application/json" \
     -d "{\"out\":true,\"bolt11\":\"$BOLT11\"}"
   ```
4. Phoenixd routes the outbound payment, your personal wallet receives it.

(Or log into LNbits UI at `http://<dockge-host>:5000`, click into the operator wallet, click "Send", paste the bolt11 — same effect.)

---

## What can go wrong + how to recover

| Symptom | Likely cause | Fix |
|---|---|---|
| Stack won't start: `phoenixd` unhealthy | First-boot taking longer than 30s | Wait. If still unhealthy after 5 min, check `docker logs espresso-phoenixd` for errors. |
| Stack won't start: `lnbits` exits with `phoenix.conf missing` | Race; phoenixd not done writing its config | The bootstrap waits up to 60s. If it still fails, restart the stack — phoenixd should be ready on second try. |
| `/onboard` returns 500 with `usermanager/api/v1/users -> 404` | Old espresso-app image cached locally | `docker compose pull espresso-app && docker compose up -d espresso-app` |
| Topup QR appears but payment never confirms | Personal wallet failed to find a route, or invoice expired | Generate a fresh QR. Verify your personal wallet has channel capacity. |
| Channel-open fee is higher than expected on first topup | One-time fee, ~$1.50 minimum | Expected. Subsequent topups within channel capacity are nearly free. |
| LNbits UI says "first install" again after restart | The credentials file was lost (volume wipe) | Delete `lnbits-data` volume entirely and let it re-init from scratch. **You'll lose all sub-wallets.** Don't do this on a real deployment unless you've already swept funds. |
| Lost the seed phrase | Cannot recover from this. | Sweep funds out before destroying the stack. Re-deploy fresh. |

---

## Rolling back to FakeWallet (for safety while you set things up)

If you want to test gifts/drinks without any real Lightning involvement, you can opt out of Phoenixd:

1. Comment out the `phoenixd` service in compose
2. Remove the `LNBITS_BACKEND_WALLET_CLASS: PhoenixdWallet` env from lnbits
3. Remove the `phoenixd-data` volume mount on lnbits
4. Redeploy

LNbits will fall back to FakeWallet (1 billion fake sats), the espresso-app still works for everything except real top-ups. The gift flow still works because it's an internal LNbits transfer.

To switch back to real Lightning later: re-add Phoenixd and redeploy. **Your sub-wallet balances persist** because they're in `lnbits-data`. But the FakeWallet "balance" was never real, so any "topups" you did with FakeWallet vanish.

---

## When to seek help

- If `docker logs espresso-lnbits` shows `Connecting to backend PhoenixdWallet... [error]` after start — Phoenixd isn't reachable. Check the network, the `PHOENIXD_API_PASSWORD` env, and that the `phoenixd-data:/phoenixd-data:ro` mount on lnbits is in place.
- If you've sent a topup payment but Phoenixd shows "incoming payment failed" in its logs — paste the failure into a GitHub issue with the amount and time. Could be a peer routing issue.
- If the channel-open fee is unexpectedly high (>5%) — check `mempool.space` for current on-chain fee rates. ACINQ's channel-open includes the on-chain transaction fee; high mempool periods are expensive. Can wait a day for fees to drop, or accept the cost.

## Appendix: the credentials file

`docker exec espresso-lnbits cat /data/admin.json` returns:

```json
{
  "username": "admin",
  "password": "<random 16-byte url-safe>",
  "lnbits_url": "http://lnbits:5000",
  "note": "Generated by lnbits-init. Bookmark this URL or rotate the password via the LNbits UI."
}
```

This is the LNbits *web UI* admin (super-user) credentials. The espresso-app doesn't use these — it uses the wallet's adminkey, which it auto-discovers from the SQLite DB via the read-only `lnbits-data` mount.

If you want to change the password after first-install, do it via the LNbits UI: `http://<dockge-host>:5000` → log in with current creds → top-right user icon → Account → change password.
