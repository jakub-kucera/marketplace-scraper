#!/bin/sh
# Writes /etc/tor/torrc fresh on every start and execs tor as PID 1 (so it receives signals
# directly - compose's `restart: always` and `down` both depend on that). The previous image's
# entrypoint hashed $PASSWORD into HashedControlPassword at startup rather than baking a hash
# into the image, so the same container image works with any password set at deploy time; this
# keeps that behavior, read from the same $PASSWORD env var the compose file already sets.
set -eu

: "${PASSWORD:?PASSWORD env var must be set (the control port password ip_changer authenticates with)}"

HASHED="$(tor --hash-password "$PASSWORD" | tail -n 1)"

cat > /etc/tor/torrc <<EOF
SocksPort 0.0.0.0:9050 IsolateDestAddr
ControlPort 0.0.0.0:9051
HashedControlPassword $HASHED
Log notice stderr
DataDirectory /var/lib/tor
User debian-tor
EOF

exec tor -f /etc/tor/torrc
