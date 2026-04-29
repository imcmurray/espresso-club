# Operations runbook

Day-to-day ops for running the espresso club.

## Onboarding a new member

**Self-serve (recommended):**

1. They visit `http://<pi-ip>:8080/onboard` on their phone (or scan the QR
   posted near the machine).
2. They enter their name and submit.
3. They have 30 seconds to tap their NFC card on the office reader.
4. They scan the top-up QR shown on the screen with a Lightning wallet
   (Wallet of Satoshi, Strike, Phoenix, Alby, Cash App).

**Slack-driven:**

1. They DM the bot: `/espresso join`.
2. The bot replies with a link to the onboarding page.
3. Same as above from step 2.

## Topping up

Three flows:

1. **At the machine**: tap card → "low balance" message → scan QR.
2. **From phone**: bookmark `/topup/<id>`, scan QR with LN wallet.
3. **Slack**: `/espresso topup [amount]` returns a link.

Lightning Address top-up (no QR needed):

If the user wants the simplest possible path, configure their LN wallet to
auto-pay your operator address (`espresso@yourdomain.com`) on a schedule. Most
wallets support this via "scheduled payments" or zaps.

## Refilling consumables

The system doesn't track physical inventory — that's overkill. But a couple of
optional niceties:

- **`/refill` Slack command** (TODO): logs "Bean refill — date, weight, cost"
  to the ledger as an `adjustment` entry. Useful for analyzing whether the
  flat per-drink price is covering actual costs.
- **Calendar reminder**: every Friday, check bean level. Order if < 1kg left.

## Withdrawing the operator wallet

Money flows: user wallets → operator wallet (on every drink) → your personal
Lightning wallet (when you sweep).

To sweep:

1. In LNbits admin, open the operator wallet.
2. Generate or paste an invoice from your personal LN wallet (or use
   "Send via Lightning Address" if the LNbits SendBack extension is enabled).
3. Pay it. Funds land in your personal wallet within seconds.

Cadence: monthly is fine. The operator wallet doesn't need to be empty —
keep ~$50–100 there for liquidity.

## Pricing tweaks

Edit `/project/bitcoin-idea/app/drinks.yaml`. Restart the app:

```bash
docker compose -f /docker/espresso-club/docker-compose.yml restart espresso-app
```

No DB migration needed — drinks are read fresh from the YAML at boot.

## Adjusting the BTC/USD rate

In dev mode the rate is hardcoded (`BTC_USD_RATE` env var, default $50,000).
For production you should:

- Either set it manually whenever it drifts more than 10% (espresso prices
  aren't sensitive to exchange-rate noise).
- Or wire in a real price feed — easiest is to hit Mempool.space's
  `https://mempool.space/api/v1/prices` endpoint every 5 min in a tiny
  background task. Left as a future enhancement; not required for v1.

## Auditing

- **Per-user history**: `SELECT * FROM ledger WHERE user_id = ?` in the
  espresso DB (sqlite at `/var/lib/docker/volumes/espresso-club_espresso-data/_data/espresso.sqlite3`).
- **Monthly summary**: `/admin` shows leaderboards and recent activity.
- **LNbits source of truth**: every wallet's balance and transaction history
  is in LNbits. The espresso DB is a convenience cache for analytics, not the
  authoritative ledger.

## Disaster recovery

| Failure                              | Recovery                                                    |
|--------------------------------------|-------------------------------------------------------------|
| SD card dies                         | Reflash, restore the three Docker volumes from backup        |
| Phoenixd container's volume corrupts | Restore volume from backup; if no backup, restore from seed |
| LNbits DB corrupts                   | Restore from backup; balances are authoritative there       |
| Forgotten Phoenixd seed              | Channel funds are recoverable via ACINQ's static_remote_key |
| Espresso DB corrupts                 | LNbits balances still intact; rebuild ledger as desired     |

The seed is the only thing whose loss is permanent. Everything else can be
rebuilt.

## Security notes

- LNbits admin UI exposes all sub-wallet keys to anyone who reaches it.
  Bind it to localhost only (`127.0.0.1:5000`) or put it behind a reverse
  proxy with auth.
- The espresso app's `/admin` route is unauthenticated — fine on a LAN, but
  add HTTP basic auth if you expose it.
- Phoenixd's REST API password is in `phoenix.conf` — don't commit `.env`
  with the password to git.
- NFC cards are MIFARE Classic, which is *trivially* clonable. Treat the
  card UID as identifying, not authenticating. For an office honor system
  this is fine — the social cost of cloning a coworker's card is much higher
  than the financial gain ($0.40 espresso). Don't use this design for
  high-value transactions.
