# Phoenixd: switching from FakeWallet to real Lightning

This is the migration path from dev (no real LN traffic) to production
(self-custodial Lightning via Phoenixd).

## Why Phoenixd

- **Tiny** — single binary, ~100 MB RAM, no Bitcoin Core required.
- **Auto-managed channels** — opens a channel with ACINQ's LSP on first
  inbound payment. You never think about liquidity.
- **Self-custodial** — your seed, your funds.
- **REST API** — drop-in funding source for LNbits.

ACINQ takes a small fee on inbound liquidity (one-time channel-open + a small
percentage on incoming payments). For an espresso club where flow is mostly
$5–$20 top-ups, this is pennies.

## First boot

```bash
cd /docker/espresso-club
cp .env.example .env

# Start ONLY phoenixd so we can capture the seed and password.
docker compose --profile phoenixd up -d phoenixd

# Tail logs — phoenixd will print a 12-word seed phrase on first run.
# **IT WILL ONLY PRINT IT ONCE. WRITE IT DOWN OFFLINE NOW.**
docker logs -f espresso-phoenixd
```

The seed is the keys to the wallet. If the container's volume is destroyed and
you don't have the seed written down, the funds are unrecoverable.

After it boots, find the auto-generated HTTP password:

```bash
docker exec espresso-phoenixd cat /phoenix/.phoenix/phoenix.conf | grep http-password
```

## Wire LNbits into Phoenixd

Edit `.env`:

```bash
LNBITS_BACKEND_WALLET_CLASS=PhoenixdWallet
PHOENIXD_API_ENDPOINT=http://phoenixd:9740/
PHOENIXD_API_PASSWORD=<the password from phoenix.conf>
```

Bring everything up:

```bash
docker compose --profile phoenixd up -d
```

LNbits should now show a real (small) sats balance once you fund the Phoenixd
wallet. Visit `http://localhost:5000`, log in as the admin user, and verify the
backend shows "PhoenixdWallet · connected".

## Funding the wallet

Phoenixd auto-opens a channel on first inbound payment. To get inbound
liquidity:

1. Take any small amount of Lightning sats (e.g. 10,000 sats from a personal
   wallet).
2. Visit LNbits, create an invoice on the operator wallet, pay it from your
   personal wallet.
3. Phoenixd opens an ACINQ channel; channel-open fee is deducted from the
   inbound payment. Subsequent inbound payments don't trigger a new channel.

## Backups

Phoenixd's seed is the only thing that matters. Channel state is recoverable
from the seed via `phoenix-cli` because ACINQ's LSP is the counterparty and
publishes static_remote_key. So:

- **Critical**: 12-word seed, written offline.
- **Nice-to-have**: snapshot of `/phoenix/.phoenix/` (not strictly required for
  recovery, but speeds it up).

Daily snapshot:

```bash
# Run from cron on the host.
docker run --rm \
  -v espresso-club_phoenixd-data:/data \
  -v /backup/phoenixd:/backup \
  alpine tar czf /backup/phoenixd-$(date +%F).tgz -C /data .
```

## Operator wallet vs. user wallets

LNbits gives every staff member a sub-wallet. When someone buys a drink, the
espresso app does an internal transfer:

```
user's sub-wallet  --[invoice]-->  operator wallet
```

Internal transfers in LNbits don't actually hit Phoenixd (LNbits short-circuits
them as DB updates). So the only times Phoenixd sees real Lightning traffic
are:

1. **Top-ups** (sats flow IN from outside).
2. **Operator withdrawals** (you sweep the operator wallet to your personal
   wallet to actually buy beans/milk).

Both paths trigger ACINQ's small fees. Budget ~1–2% overhead.

## Migrating away from Phoenixd

If you outgrow it (say, the espresso fund balloons into the thousands and you
want lower fees / a public node), the path is:

1. Spin up an LND or Core Lightning node alongside.
2. Open channels from there to a few well-connected nodes for inbound.
3. Switch LNbits funding source to LndRestWallet or CoreLightningRestWallet.
4. Migrate the operator wallet's balance over by paying yourself an invoice.

But for $200/mo flow, Phoenixd is correct.
