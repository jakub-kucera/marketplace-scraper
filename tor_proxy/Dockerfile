# Replaces `dperson/torproxy` (see docs/BACKUPS.md-style rationale: don't trust an external
# prebuilt image long-term). That image's last publish was 2021 and bundled Tor 0.4.4.8; the
# live Tor network raised its minimum required protocol versions since, and an old client
# simply cannot bootstrap a circuit anymore — found 2026-11-02 as a 72h production outage,
# every tor_proxy start crash-looping on "required ... not supported by this version of Tor".
# Debian's own tor package tracks security updates and stays current on every rebuild, which
# a 5-year-frozen Docker Hub image never will.
FROM debian:bookworm-slim

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends tor; \
    rm -rf /var/lib/apt/lists/*; \
    tor --version

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 9050 9051

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
