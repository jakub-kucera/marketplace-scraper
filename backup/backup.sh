#!/usr/bin/env bash
#
# Nightly Postgres backup. See docs/BACKUPS.md for the reasoning behind every
# choice here; the short version:
#
#   local copy   uncompressed, keep a few. The fast path for "a migration ate
#                the ads last night and I'm already on the box".
#   restic copy  compressed + deduplicated + encrypted, off-host, long retention.
#                Covers the failures that take the Pi with them (§3.1).
#
# The dump is written with -Z0 deliberately. pg_dump's own compression yields a
# different byte stream every night even when the data barely moved, which
# defeats restic's content-defined chunking. Uncompressed input lets restic
# dedupe consecutive dumps and apply its own zstd — compression AND dedup,
# instead of one or the other.
#
# Off-host backup is optional at runtime: with no RESTIC_REPOSITORY configured
# this still takes and rotates local dumps, and says so. That way the sidecar
# can ship before a B2 account exists without wedging the deploy.

set -euo pipefail

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_BACKUP_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-}"

# Runs once and exits. Scheduling is a systemd timer on the host
# (backup/systemd/), not a sleep loop in here — see docs/BACKUPS.md §5.
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP_LOCAL="${BACKUP_KEEP_LOCAL:-3}"

# Retention caps at ~6 months to stay inside the PII window MONETIZATION.md §6.1
# commits to. A backup that outlives the purge is not a purge (docs/BACKUPS.md §7).
BACKUP_KEEP_DAILY="${BACKUP_KEEP_DAILY:-7}"
BACKUP_KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-4}"
BACKUP_KEEP_MONTHLY="${BACKUP_KEEP_MONTHLY:-6}"

# Containers get a fresh random hostname on every recreate. restic groups
# snapshots by host, so letting it default would scatter the history across
# dozens of hosts and quietly break `forget`'s retention policy.
RESTIC_HOST="${RESTIC_HOST:-marketplace-pi}"

# Alerting goes through env, not the Discord table in Postgres. A backup alert
# that needs a working database cannot report a broken database.
WEBHOOK="${BACKUP_DISCORD_WEBHOOK_URL:-${DISCORD_LOGGER_WEBHOOK_URL:-}}"

log() { echo "[backup] $(date '+%F %T') $*"; }

notify() {
    local message="$1"
    [ -n "$WEBHOOK" ] || { log "no webhook configured, not sending: $message"; return 0; }
    jq -n --arg c "$message" '{content: $c}' \
        | curl -fsS -m 20 -X POST -H 'Content-Type: application/json' -d @- "$WEBHOOK" \
        >/dev/null 2>&1 \
        || log "WARNING: failed to post to Discord"
}

wait_for_postgres() {
    local waited=0
    until pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" >/dev/null 2>&1; do
        waited=$((waited + 3))
        [ "$waited" -ge 300 ] && { log "postgres unreachable after ${waited}s"; return 1; }
        sleep 3
    done
}

take_dump() {
    local target="$1"
    pg_dump -Fc -Z0 \
        -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -f "$target"
}

prune_local() {
    # shellcheck disable=SC2012  # filenames are ours and timestamped; ls -t is fine
    ls -1t "$BACKUP_DIR"/scraper-*.dump 2>/dev/null \
        | tail -n +$((BACKUP_KEEP_LOCAL + 1)) \
        | while read -r old; do
            log "pruning local $(basename "$old")"
            rm -f "$old"
        done
}

push_offsite() {
    local dump="$1"

    if [ -z "${RESTIC_REPOSITORY:-}" ]; then
        log "RESTIC_REPOSITORY unset — local dump only, nothing left this host"
        return 0
    fi
    if [ -z "${RESTIC_PASSWORD:-}" ] && [ -z "${RESTIC_PASSWORD_FILE:-}" ]; then
        log "ERROR: RESTIC_REPOSITORY set but no RESTIC_PASSWORD/RESTIC_PASSWORD_FILE"
        return 1
    fi

    if ! restic cat config >/dev/null 2>&1; then
        log "initialising restic repository at $RESTIC_REPOSITORY"
        restic init
    fi

    log "uploading to restic"
    restic backup --host "$RESTIC_HOST" --tag nightly "$dump"

    log "applying retention ${BACKUP_KEEP_DAILY}d/${BACKUP_KEEP_WEEKLY}w/${BACKUP_KEEP_MONTHLY}m"
    restic forget \
        --host "$RESTIC_HOST" --tag nightly \
        --keep-daily "$BACKUP_KEEP_DAILY" \
        --keep-weekly "$BACKUP_KEEP_WEEKLY" \
        --keep-monthly "$BACKUP_KEEP_MONTHLY" \
        --prune
}

# Weekly "last good backup" post, so silence is itself informative — an alert
# that only fires on failure is indistinguishable from a dead alerter.
maybe_heartbeat() {
    local dump="$1" size="$2"
    [ "$(date +%u)" = "1" ] || return 0
    local remote="local only"
    [ -n "${RESTIC_REPOSITORY:-}" ] && remote="restic ok"
    notify ":floppy_disk: Backup heartbeat — last good: $(date '+%F %T'), $(basename "$dump"), ${size}, ${remote}"
}

run_backup() {
    mkdir -p "$BACKUP_DIR"
    wait_for_postgres || return 1

    local dump="$BACKUP_DIR/scraper-$(date +%F-%H%M%S).dump"
    log "dumping $POSTGRES_DB → $(basename "$dump")"
    take_dump "$dump"

    local size
    size="$(du -h "$dump" | cut -f1)"
    log "dump complete ($size)"

    push_offsite "$dump"
    prune_local
    maybe_heartbeat "$dump" "$size"
    log "done"
}

main() {
    log "starting (keep ${BACKUP_KEEP_LOCAL} local, repo ${RESTIC_REPOSITORY:-<none>})"

    # Alert from in here rather than relying on systemd's OnFailure, so a failure
    # is reported the same way however the container was invoked.
    if ! run_backup; then
        log "ERROR: backup failed"
        notify ":rotating_light: **Backup FAILED** on ${RESTIC_HOST} at $(date '+%F %T'). Check \`journalctl -u marketplace-backup\`."
        return 1
    fi
}

main "$@"
