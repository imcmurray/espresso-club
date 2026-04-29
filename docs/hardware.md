# Hardware deployment (Raspberry Pi)

End-to-end guide from "I have a Pi in a box" to "espresso machine accepts taps."

## Bill of materials

| Item                              | Cost       | Notes                                   |
|-----------------------------------|------------|-----------------------------------------|
| Raspberry Pi 4 (4 GB)             | ~$55       | 2GB works but tight; 8GB if you can     |
| Official 7" touchscreen           | ~$80       | DSI cable; or HDMI 5"–10" panel         |
| Pi case + PSU + 32 GB microSD     | ~$30       | Argon NEO if mounting under shelf       |
| PN532 NFC module (USB or I²C)     | ~$15       | Adafruit's red board is well-supported  |
| Shelly Plus 1 smart relay         | ~$20       | Wi-Fi controlled, 16 A capable          |
| MIFARE Classic 1K cards (50-pack) | ~$15       | $0.30 each                              |
| Misc cables, USB-A cable for NFC  | ~$10       |                                         |
| **Total**                         | **~$225**  |                                         |

## Wiring the grinder relay

> ⚠️ Mains voltage. If you've never wired a UK/US/EU plug before, ask someone who has, or use a smart plug with built-in mains (Shelly Plus Plug US/UK/EU) instead of the bare relay.

Standard Shelly Plus 1 inline-relay wiring:

```
   Wall outlet (mains L) ───► Shelly L (in) ───► Shelly O (out) ───► Grinder L
   Wall outlet (mains N) ───────────────────────────────────────────► Grinder N
   Wall outlet (mains E) ───────────────────────────────────────────► Grinder E
                                  │
                                  └─ Shelly N (in) for relay logic power
```

The relay opens/closes the live (L) wire only. Neutral and earth pass through.

Test before mounting: with the Shelly running, hit the test endpoint:

```
http://<shelly-ip>/rpc/Switch.Toggle?id=0
```

You should hear a click and the grinder should power on. Toggle again — off.

## NFC reader

PN532 over USB is simplest. Plug it into the Pi, then:

```bash
lsusb | grep -i nfc
# expect: NXP Semiconductors PN532 ...
sudo usermod -aG plugdev $USER   # if needed
```

For I²C (cleaner mount, no USB cable):

1. Set the PN532 jumpers to I²C mode (consult the board's silkscreen).
2. Wire SDA → Pi GPIO 2, SCL → Pi GPIO 3, 3V3 → Pi 3V3, GND → Pi GND.
3. `sudo raspi-config` → enable I²C.
4. Set `NFC_DEVICE=i2c:/dev/i2c-1` in `.env`.

## Mounting on the wall

The touchscreen stand sits next to the espresso machine. Pi mounts behind the
screen. Two cables leave the cluster:

- USB cable to the PN532 (mounted on a flat surface where people will tap)
- Power cable to the Shelly relay's outlet

The Shelly itself sits inside a junction box on the wall, controlling the
grinder's outlet.

## Software install on the Pi

Assuming Raspberry Pi OS (Bookworm) 64-bit, freshly imaged:

```bash
# 1. Update + install Docker
sudo apt update && sudo apt full-upgrade -y
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker pi
newgrp docker  # or log out + back in

# 2. Clone the repo
git clone <your-repo-url> /opt/espresso-club
cd /opt/espresso-club

# 3. Configure
cp /docker/espresso-club/.env.example /docker/espresso-club/.env
${EDITOR:-nano} /docker/espresso-club/.env
# - set RELAY_DRIVER=shelly
# - set SHELLY_HOST=192.168.1.50  (or whatever your Shelly's IP is)
# - set TAP_SIMULATOR=false
# - set LNBITS_BACKEND_WALLET_CLASS=PhoenixdWallet (if going live)

# 4. Build + start
cd /docker/espresso-club
docker compose --profile phoenixd up -d --build

# 5. Boot the touchscreen UI in kiosk mode
sudo apt install chromium-browser unclutter
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/espresso-kiosk.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Espresso Kiosk
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:8080/menu
EOF
```

## Daily operations

- **First time setup**: each staff member visits `http://<pi-ip>:8080/onboard`
  on their phone (Pi's LAN-local IP), enters their name, then taps a card on
  the office reader within 30s.
- **Top-ups**: `http://<pi-ip>:8080/topup/<their-id>` — bookmarkable.
- **Refilling beans/milk**: nothing to do in the system. Optional: post a
  `/refill` Slack command that logs the date in the admin dashboard.
- **Withdrawing the kitty**: log into LNbits (`:5000`), pay yourself an invoice
  from the operator wallet to your personal Lightning wallet, use the funds to
  buy beans.

## Backup checklist

- **Phoenixd seed (12 words)**: written offline, in a safe. Most important.
- **`/var/lib/docker/volumes/espresso-club_phoenixd-data`**: full snapshot,
  daily, encrypted offsite.
- **`/var/lib/docker/volumes/espresso-club_lnbits-data`**: same.
- **`/var/lib/docker/volumes/espresso-club_espresso-data`**: same; this is the
  ledger.

The cron `scripts/backup.sh` (TODO: write me) tars all three volumes nightly.

## Troubleshooting

- **Touchscreen blank** — check HDMI/DSI cable, run `vcgencmd get_config int`
  on the Pi to verify display config.
- **NFC not detected** — `python3 -m nfc` should report the reader; if not,
  re-seat the USB cable, check `dmesg`.
- **Shelly unreachable** — ping it; it should be on the office Wi-Fi with a
  static lease. Check the Shelly app.
- **LNbits fails to connect to Phoenixd** — verify the password in
  `phoenix.conf` matches `PHOENIXD_API_PASSWORD` in `.env`. Restart both
  containers in order: phoenixd, then lnbits.
- **"insufficient balance" when user has just topped up** — LNbits balance
  reads have a small lag; wait 2–3 seconds, retry.
- **Build fails with apparmor errors** — only seen in some LXC hosts. Real
  Raspberry Pi OS doesn't hit this. If it does, set `"apparmor": false` in
  `/etc/docker/daemon.json` and restart Docker.
