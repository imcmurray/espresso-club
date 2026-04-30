#!/usr/bin/env bash
# Restore a Phoenixd wallet from its 12-word BIP39 seed phrase.
#
# Usage:
#   ./scripts/phoenixd-restore-seed.sh
#   The script will prompt for the 12 words on stdin.
#
# Or pipe them in non-interactively:
#   echo "word1 word2 word3 ... word12" | ./scripts/phoenixd-restore-seed.sh
#
# Or read from a file:
#   ./scripts/phoenixd-restore-seed.sh < my-seed.txt
#
# Pre-conditions:
#   - The espresso-club stack must be DOWN. The Phoenixd container can't be
#     using the volume while we write to it.
#   - Run as root (or with sudo) so docker can create/inspect volumes.
#
# Post-conditions:
#   - The Phoenixd data volume exists and contains seed.dat with your words.
#   - Bringing the stack back up will boot Phoenixd with that identity.
#     ACINQ will re-establish your channels within ~30 seconds.

set -euo pipefail

VOLUME="${PHOENIXD_VOLUME:-espresso-club_phoenixd-data}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/stacks/espresso-club}"

err() { echo "error: $*" >&2; exit 1; }
log() { echo "[restore] $*"; }

# Refuse to run if Phoenixd is currently running — would race on the seed file.
if docker ps --format '{{.Names}}' | grep -qx 'espresso-phoenixd'; then
    err "espresso-phoenixd is currently running. Stop the stack first:
       sudo docker compose -f $COMPOSE_DIR/compose.yaml down"
fi

# Read seed words.
if [ -t 0 ]; then
    echo "Paste your 12-word BIP39 seed phrase (one line, words separated by"
    echo "spaces). Press Enter, then Ctrl-D to finish:"
fi
SEED="$(cat)"

# Sanity-check: must be 12 (or 24) words, lowercase letters only.
WORD_COUNT=$(echo "$SEED" | tr -s '[:space:]' ' ' | wc -w)
if [ "$WORD_COUNT" != "12" ] && [ "$WORD_COUNT" != "24" ]; then
    err "expected 12 or 24 words, got $WORD_COUNT.
       Re-run and paste exactly what 'cat /phoenix/.phoenix/seed.dat' produced
       on the original Phoenixd container."
fi

# Check each word is plausible (BIP39 wordlist is all lowercase a-z, 3-8 chars).
for w in $SEED; do
    if ! echo "$w" | grep -qE '^[a-z]{3,8}$'; then
        err "word '$w' doesn't look like a BIP39 word (lowercase a-z, 3-8 chars)"
    fi
done

# Idempotent volume create.
if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    log "creating volume $VOLUME..."
    docker volume create "$VOLUME" >/dev/null
fi

# Refuse to overwrite an existing seed.dat without explicit confirmation.
EXISTING=$(docker run --rm -v "$VOLUME":/data alpine sh -c \
    'test -f /data/seed.dat && cat /data/seed.dat || true' 2>/dev/null)
if [ -n "$EXISTING" ]; then
    log "seed.dat already exists in $VOLUME. First word currently: $(echo "$EXISTING" | awk '{print $1}')"
    read -p "Overwrite with the seed you just provided? [y/N] " yn
    case "$yn" in
        [yY]|[yY][eE][sS]) ;;
        *) err "aborted; existing seed.dat preserved" ;;
    esac
fi

# Write the seed, fix permissions for the phoenix user (uid 1000 in the image).
echo "$SEED" | docker run --rm -i -v "$VOLUME":/data alpine sh -c '
    cat > /data/seed.dat
    chown 1000:1000 /data/seed.dat
    chmod 600 /data/seed.dat
    echo "wrote /data/seed.dat ($(wc -w < /data/seed.dat) words, $(stat -c %s /data/seed.dat) bytes)"
'

log "done. Bring the stack back up:"
log "  sudo docker compose -f $COMPOSE_DIR/compose.yaml up -d"
log ""
log "Then watch the logs to confirm Phoenixd identifies as your previous node:"
log "  sudo docker logs -f espresso-phoenixd | grep nodeid"
log ""
log "ACINQ will re-establish channels within 30 seconds. Funds in those"
log "channels become available again automatically."
