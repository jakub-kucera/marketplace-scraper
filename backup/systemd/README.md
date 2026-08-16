# Backup timer — install on the Pi

The backup is a **one-shot container** run by a systemd timer, not a long-running
service. Nothing idles between runs. See [`docs/BACKUPS.md`](../../docs/BACKUPS.md) §5.

These units live in the repo so re-provisioning the Pi is one command, not
tribal knowledge.

```bash
cd /home/user/marketplace-scrapper
sudo cp backup/systemd/marketplace-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now marketplace-backup.timer
```

If the checkout is not at `/home/user/marketplace-scrapper`, edit
`WorkingDirectory=` in the `.service` first.

## Verify

```bash
systemctl list-timers marketplace-backup.timer   # next scheduled run
sudo systemctl start marketplace-backup.service  # force one now
journalctl -u marketplace-backup -n 50 --no-pager
ls -lh backups/
```

## Notes

- `Persistent=true` means a run missed while the Pi was off happens on next boot,
  rather than being skipped silently.
- The timer only schedules. Credentials, retention and the restic repo all come
  from `.env` via compose — nothing is configured twice.
- Failure alerts are posted by the script itself (Discord), so they fire the same
  way whether systemd or you invoked it.
