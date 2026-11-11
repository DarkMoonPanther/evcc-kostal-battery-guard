#!/bin/sh
# Installer never starts/stops/enables any systemd service.
set -eu
MODE="$1"
SRC="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TARGET="/opt/battery-control-guard"
CONF="/etc/battery-control-guard"
UNIT="/etc/systemd/system/battery-control-guard.service"
case "$MODE" in
  --dry-run)
    printf '%s\n' \
      "DRY RUN ONLY. Nothing changed." \
      "Source: $SRC" \
      "Will create user bcguard and $TARGET, $CONF, $UNIT" \
      "Will not stop or start existing service, or activate new service." \
      "Existing config never overwritten. Default config disarmed." \
      "Explicit --install is needed for installation; starting requires a separate operator action."
    ;;
  --install)
    [ "$(id -u)" -eq 0 ] || { echo "Run as root for installation" >&2; exit 2; }
    [ ! -e "$TARGET" ] || { echo "Target exists: refuse replacement; backup/upgrade required" >&2; exit 2; }
    [ ! -e "$UNIT" ] || { echo "Unit exists: refuse replacement" >&2; exit 2; }
    if ! getent passwd bcguard >/dev/null; then
      useradd --system --home-dir /var/lib/battery-control-guard --shell /usr/sbin/nologin bcguard
    fi
    install -d -m 0755 "$TARGET"
    cp -r "$SRC/battery_control_guard" "$TARGET/"
    find "$TARGET" -type d -name __pycache__ -prune -exec rm -rf '{}' +
    chown -R root:root "$TARGET"
    find "$TARGET" -type f -exec chmod 0644 '{}' +
    find "$TARGET" -type d -exec chmod 0755 '{}' +
    install -d -m 0750 -o root -g bcguard "$CONF"
    if [ ! -e "$CONF/config.toml" ]; then
      install -m 0640 -o root -g bcguard "$SRC/config.example.toml" "$CONF/config.toml"
    fi
    install -d -m 0700 -o bcguard -g bcguard /var/lib/battery-control-guard
    install -m 0644 -o root -g root "$SRC/battery-control-guard.service" "$UNIT"
    systemctl daemon-reload
    echo "Installed disarmed files. NOT enabled or started."
    echo "Before enabling: configure, migrate ledgers, test observe, stop legacy services, verify 1040 baseline."
    ;;
  *)
    echo "Usage: $0 --dry-run|--install" >&2
    exit 2
    ;;
esac
