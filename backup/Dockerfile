# Backup sidecar — see docs/BACKUPS.md §5.
#
# Built FROM the same postgres image the server runs so the pg_dump client
# version matches the server by construction. A host-installed client drifts
# out of version on a long-lived Pi; this cannot.
FROM postgres:15.2

# Debian bullseye ships restic 0.12, which predates repo format v2 and so has no
# native compression — the whole reason we dump with -Z0 (see backup.sh). Pull a
# modern binary instead. Bump this ARG to upgrade.
ARG RESTIC_VERSION=0.17.3

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl bzip2 jq; \
    rm -rf /var/lib/apt/lists/*; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) restic_arch='amd64' ;; \
        arm64) restic_arch='arm64' ;; \
        armhf) restic_arch='arm' ;; \
        *) echo "unsupported architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/restic.bz2 \
        "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_${restic_arch}.bz2"; \
    bunzip2 -c /tmp/restic.bz2 > /usr/local/bin/restic; \
    chmod +x /usr/local/bin/restic; \
    rm -f /tmp/restic.bz2; \
    restic version

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

ENTRYPOINT ["/usr/local/bin/backup.sh"]
