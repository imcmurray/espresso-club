# Dockge deployment

Drop-in stack file for [Dockge](https://github.com/louislam/dockge).

## Use

1. **Dockge UI** → **Compose** → **New Stack**.
2. Name it `espresso-club`.
3. Paste [`compose.yaml`](./compose.yaml) into the editor.
4. (Optional) Switch to the **Env** tab and set any of:
   - `ESPRESSO_TAG=<git-sha>` to pin the app/nfc/slack images to a specific build (default: `latest` follows the most recent push to main).
   - `RELAY_DRIVER=shelly` + `SHELLY_HOST=192.168.1.50` once your relay is wired.
   - `TAP_SIMULATOR=false` once a real PN532 is plugged into the host.
5. **Deploy**.

Dockge runs `docker compose pull` then `up -d` and the stack lights up in ~1 minute.

## URLs after deploy

| What | Where |
|---|---|
| Touchscreen UI | http://`<dockge-host>`:8080/menu |
| Operator admin | http://`<dockge-host>`:8080/admin |
| LNbits admin | http://`<dockge-host>`:5000 |
| NFC simulator (POST) | http://`<dockge-host>`:9999/tap |

## Customizing the drinks menu

The defaults are baked into the app image. To change prices or add drinks
without forking the repo, after Dockge creates the stack directory (typically
`/opt/stacks/espresso-club/`):

1. Drop your edited `drinks.yaml` into that directory.
2. Add a bind mount under the `espresso-app` service:
   ```yaml
   volumes:
     - espresso-data:/data
     - ./drinks.yaml:/app/drinks.yaml:ro
   ```
3. Redeploy from Dockge.

## Going live with real Lightning

The Phoenixd and Slack-bot blocks are commented out at the bottom of
`compose.yaml`. Uncomment what you want and follow:

- [`docs/phoenixd.md`](../../docs/phoenixd.md) — seed-handling, LNbits wiring.
- [`docs/operations.md`](../../docs/operations.md) — top-up/withdraw flow.

## Updating

Dockge has a one-click "Update" that does `docker compose pull && up -d`.
Because both `app:latest` and pinned `app:<sha>` images are kept on GHCR,
rolling back to a known-good build is just changing `ESPRESSO_TAG` in Dockge's
Env tab and clicking Update.
