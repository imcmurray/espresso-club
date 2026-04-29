#!/usr/bin/env bash
# Print the LNbits admin (super-user) URL for the running stack.
#
# LNbits auto-generates a "super user" on first boot. That account has full
# admin rights and is distinct from any wallet you create through the UI. This
# script reads the super-user ID out of the running container and prints the
# bookmarkable URL to log in as that admin.
#
# Usage:
#   ./scripts/lnbits-admin-url.sh
#   ./scripts/lnbits-admin-url.sh espresso-lnbits   # custom container name
#   HOST=192.168.1.210 ./scripts/lnbits-admin-url.sh
#
# You usually don't need this — the espresso app talks to LNbits over the API
# and the operator never touches its UI. Run it only when you want to poke
# around LNbits' admin pages directly.

set -euo pipefail

CONTAINER="${1:-espresso-lnbits}"
HOST="${HOST:-localhost}"
PORT="${PORT:-5000}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "error: container '$CONTAINER' is not running." >&2
    echo "       run 'docker ps' to see the actual name, or pass it as \$1." >&2
    exit 1
fi

# LNbits writes the super-user ID to /data/.super_user on first boot (with
# LNBITS_ADMIN_UI=true). On older versions it only logged it.
uid=""
if uid=$(docker exec "$CONTAINER" cat /data/.super_user 2>/dev/null); then
    :
else
    # Fall back to scraping the startup log line.
    uid=$(docker logs "$CONTAINER" 2>&1 | grep -iE 'super.?user' | grep -oE '[0-9a-f]{32}' | head -n1 || true)
fi

if [ -z "$uid" ]; then
    echo "error: couldn't find super-user ID in $CONTAINER." >&2
    echo "       try: docker logs $CONTAINER 2>&1 | grep -i super" >&2
    exit 2
fi

echo "LNbits admin URL:"
echo "  http://$HOST:$PORT/wallet?usr=$uid"
echo
echo "Bookmark it. The URL is the credential — anyone with it has full admin."
