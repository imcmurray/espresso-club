# Office Espresso Club — Lightning-Powered

A fair, low-friction system for staff to chip in toward an office espresso machine,
where heavy users naturally pay more than light users, and the owner (you) is
reimbursed for beans, milk, creamer, and distilled water.

---

## Background

- **Machine ownership**: privately owned by the operator (Ian).
- **Consumables**: beans, milk, creamer, distilled water — all supplied by the operator.
- **Goal**: usage-proportional reimbursement that's fast, fair, and doesn't require anyone to remember to Venmo someone.
- **Payment rail**: Bitcoin Lightning Network — sub-cent fees, sub-second confirmation, no payment processor middleman.

---

## Design model: Prepaid Balance + Per-Drink Pricing

Each registered user has a small pre-funded balance (like a transit card). They
tap an NFC card or phone before a drink, the touchscreen offers a menu, and the
chosen drink's price is debited. Heavy users tap more often → pay more.

### Per-drink pricing (illustrative)

| Drink                          | Price   | Cost driver        |
|--------------------------------|---------|--------------------|
| Single espresso                | $0.40   | ~7g beans          |
| Double espresso / Americano    | $0.60   | ~14g beans         |
| Cappuccino / Cortado           | $0.90   | beans + milk       |
| Latte                          | $1.10   | beans + more milk  |
| Steamed milk / hot water only  | $0.30   | creamer/water      |

Tune to actual cost-per-drink + a small buffer for machine wear, descaler, etc.
Aim for **fair**, not profit.

### Top-up flow

User scans QR, pays $5 / $10 / $20 from any Lightning wallet, balance auto-credits within ~2 seconds.

### Why prepaid (vs. pay-per-shot live)

- Zero waiting at the machine — tap and go.
- Avoids per-payment fees and round-trips on micro-amounts.
- Same mental model as Starbucks card or transit pass.
- Top up once, drink for weeks.

---

## User experience

### First time (one-time, ~2 min)

1. Coworker DMs the bot on Slack: "I want in." (or scans an onboard QR on the machine)
2. They enter their name + tap their NFC card on the reader once → registered.
3. Scan top-up QR → pay $10 from any Lightning wallet → balance is $10.

### Every drink (~3 sec)

1. Walk up. Tap card on the reader.
2. Touchscreen: "Hi Sarah · Balance: $8.40 · Pick a drink"
3. Tap "Latte" → grinder unlocks for 30 sec → "Enjoy ($1.10) · Balance: $7.30"

### Low balance (~once per month)

- Slack DM: "Hey Sarah, your espresso balance is $1.20. Top up? [QR]"
- Scan, pay, done.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│ Espresso machine (untouched)                    │
└─────────────────────────────────────────────────┘
            ↑ power
┌─────────────────────────────────────────────────┐
│ Smart relay (Shelly Plus 1)                     │
│ Gates the GRINDER's power, not the machine      │
│ → 30-sec window per drink                       │
└─────────────────────────────────────────────────┘
            ↑ HTTP / MQTT
┌─────────────────────────────────────────────────┐
│ Raspberry Pi 4                                  │
│  - 7" touchscreen → menu UI                     │
│  - PN532 NFC reader → tap-to-identify           │
│  - LNbits (Docker) → wallet + sub-wallets       │
│  - FastAPI/HTMX app → orchestration             │
│  - SQLite → users, drinks, ledger               │
└─────────────────────────────────────────────────┘
            ↑ Lightning
┌─────────────────────────────────────────────────┐
│ Lightning node                                  │
│  Phoenixd (self-hosted) or Voltage.cloud        │
└─────────────────────────────────────────────────┘
            ↑
┌─────────────────────────────────────────────────┐
│ Slack bot                                       │
│  - Onboarding flow                              │
│  - Low-balance DM pings                         │
│  - Monthly leaderboard ("top 5 caffeine demons")│
└─────────────────────────────────────────────────┘
```

**Why gate the grinder, not the espresso machine?**
Espresso machines are slow to warm up (15+ min) and shouldn't be power-cycled.
The grinder, on the other hand, is the actual gate to making a drink and is
harmless to switch on/off. No grind = no shot.

---

## Hardware shopping list

| Item                              | Cost       | Notes                              |
|-----------------------------------|------------|------------------------------------|
| Raspberry Pi 4 (4GB)              | ~$55       | brain                              |
| Official 7" touchscreen           | ~$80       | (or 3.5" for $25 if compact)       |
| PN532 NFC reader (USB or I²C)     | ~$15       | tap surface                        |
| Shelly Plus 1 smart relay         | ~$20       | gates grinder power                |
| MIFARE NFC cards (50-pack)        | ~$15       | $0.30/staff member                 |
| Pi case + PSU + microSD           | ~$30       |                                    |
| **Total hardware (one-time)**     | **~$215**  |                                    |
| Lightning node hosting            | $0–$10/mo  | self-hosted free / Voltage $10/mo  |

Phones can substitute for cards (most modern phones can emulate NFC), so card
distribution is optional.

---

## Software stack

- **LNbits** (Docker) — multi-user wallet system, gives every staff member a
  sub-wallet with its own balance, invoices, and webhooks. Open source.
- **FastAPI + HTMX webapp** on the Pi:
  - `/onboard` — register a new user + their NFC UID
  - `/menu` — touchscreen UI: tap card → show name + balance + drink options
  - `/buy/{drink}` — debit LNbits sub-wallet, pulse the Shelly relay
  - `/topup/{user}` — generate a Lightning invoice QR for $5/$10/$20
  - `/admin` — operator view: ledger, refill log, low-balance users
- **Slack bot** (Bolt SDK) — onboarding, low-balance pings, monthly leaderboard.
- **`nfc.py` daemon** — watches the PN532, posts tap events to the webapp.
- **Lightning node** — Phoenixd (recommended, self-hosted, ACINQ) or LND via
  Voltage.cloud (managed).

Total: ~600–1000 lines of code. 1–2 evening build.

---

## Open decisions

1. **Drinks menu** — final list and prices.
2. **Lightning node** — Phoenixd self-hosted (free) or Voltage.cloud (~$10/mo, managed)?
3. **Gating** — grinder smart-plug lock, or honor-tap (no physical lock)?
4. **Slack workspace** — wire to existing? Or web-only dashboard?
5. **Headcount** — for sizing the NFC card order.

---

## Phased rollout

### Phase 0 — paper prototype (this week)

- Sign on the wall with a single QR for one Lightning Address.
- Suggested $20/month or $5/week.
- See if any contributions trickle in. Validates social will to pay.

### Phase 1 — software MVP (this weekend)

- LNbits in Docker on a dev machine.
- Webapp running locally; "NFC tap" simulated by typing a name.
- Click-through demo of the entire flow before any hardware is purchased.

### Phase 2 — hardware integration (when parts arrive)

- Mount Pi + touchscreen near the machine.
- Real PN532 NFC tap.
- Shelly relay wired to grinder power.

### Phase 3 — soft launch (1 week)

- 2–3 willing coworkers test for a week.
- Iterate on UI, drink prices, error cases.

### Phase 4 — office-wide rollout

- Print and distribute NFC cards.
- Post onboarding QR + instructions.
- Slack bot announces to channel.

### Phase 5 — niceties (later)

- E-ink "club status" display: balance, last refill date, contributor count.
- Monthly leaderboard fun in Slack.
- Public ledger if desired.
- Migrate from custodial node → self-sovereign as flow grows.

---

## Tax / legal notes (US, not legal advice)

- Lightning payments are technically taxable income to the recipient at fair
  market value when received.
- For "coworkers chipping in for coffee" at <$200/mo flow, this is functionally
  identical to a Venmo reimbursement situation — most people don't report this,
  the IRS isn't auditing your espresso fund.
- If flow grows materially, consult a tax person.

---

## Risks and mitigations

| Risk                                                                                   | Mitigation                                                                |
|----------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| Custodial wallet provider freezes funds                                                | Self-host (Phoenixd or LND) once flow > ~$200                             |
| Pi or screen fails                                                                     | Spare SD card backup; honor system fallback while replacing               |
| Someone shares an NFC card                                                             | Per-user usage logs make it visible; address socially                     |
| Grinder relay fails closed (no one can use machine)                                    | Physical bypass switch; ops monitoring                                    |
| Lightning channel runs out of inbound liquidity (top-ups fail)                         | Use an LSP (Phoenixd does this automatically); or top up channel manually |
| Lost SD card / corrupted DB → forgotten balances                                       | Daily SQLite backup to a second disk + encrypted offsite                  |
