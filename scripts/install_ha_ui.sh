#!/bin/sh
# Optional HA dashboard setup for the EXISTING Battery Control Guard project.
# Does not enable or start any service and never changes EVCC/KOSTAL settings.
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HA_CONFIG=""
MODE=install
REPLACE=no
while [ "$#" -gt 0 ]; do
  case "$1" in
    --ha-config) [ "$#" -ge 2 ] || exit 2; HA_CONFIG=$2; shift 2 ;;
    --dry-run) MODE=dry-run; shift ;;
    --replace) REPLACE=yes; shift ;;
    *) echo "Usage: sh scripts/install_ha_ui.sh --ha-config /path/to/ha/config [--dry-run] [--replace]" >&2; exit 2 ;;
  esac
done
[ -n "$HA_CONFIG" ] || { echo "HA config directory is required" >&2; exit 2; }
case "$HA_CONFIG" in
  /*) ;;
  *) echo "Use an absolute --ha-config path" >&2; exit 2 ;;
esac
# Constrain the one value that will be written to a systemd EnvironmentFile.
case "$HA_CONFIG" in
  *[!a-zA-Z0-9_./+-]*) echo "Unsupported characters in HA path; use a simple path" >&2; exit 2 ;;
esac
[ -d "$HA_CONFIG" ] && [ ! -L "$HA_CONFIG" ] || { echo "HA config dir missing/symlink: $HA_CONFIG" >&2; exit 2; }
[ -f "$HA_CONFIG/configuration.yaml" ] || { echo "Not a Home Assistant config directory (configuration.yaml missing)" >&2; exit 2; }
[ "$(id -u)" -ne 0 ] || { echo "Run as the intended HA/export user, not root" >&2; exit 2; }

WEB="$HA_CONFIG/www/guard"
USERDATA="$HOME/.local/share/battery-control-guard"
ENV_DIR="$HOME/.config/battery-control-guard"
UNIT_DIR="$HOME/.config/systemd/user"
CARD="$WEB/battery-control-guard-card.js"
EXPORTER="$USERDATA/ha_status_export.py"
ENVFILE="$ENV_DIR/ha-ui.env"
SERVICE="$UNIT_DIR/battery-control-guard-ha-export.service"
TIMER="$UNIT_DIR/battery-control-guard-ha-export.timer"
[ -d "$WEB" ] || [ ! -e "$WEB" ] || { echo "Refuse abnormal www/guard target" >&2; exit 2; }
[ ! -L "$WEB" ] || { echo "Refuse symlink www/guard target" >&2; exit 2; }

check_target(){
  target=$1; source=$2
  [ ! -L "$target" ] || { echo "Refuse symlink: $target" >&2; exit 2; }
  if [ -e "$target" ] && ! cmp -s "$source" "$target" && [ "$REPLACE" != yes ]; then
    echo "Existing file differs: $target (use --replace after backup/review)" >&2
    exit 2
  fi
}
check_target "$CARD" "$SRC/frontend/battery-control-guard-card.js"
check_target "$EXPORTER" "$SRC/scripts/ha_status_export.py"
check_target "$SERVICE" "$SRC/systemd/user/battery-control-guard-ha-export.service"
check_target "$TIMER" "$SRC/systemd/user/battery-control-guard-ha-export.timer"
if [ -e "$ENVFILE" ] && [ "$REPLACE" != yes ]; then
  prior=$(sed -n '1p' "$ENVFILE")
  [ "$prior" = "BCG_HA_PUBLIC_DIR=$WEB" ] || { echo "Existing HA export destination differs; use --replace" >&2; exit 2; }
fi
if [ "$MODE" = dry-run ]; then
  echo "DRY RUN: Would install UI, HA JSON exporter and DISABLED user timer for: $WEB"
  echo "No EVCC, KOSTAL, HA config or running service changed."
  exit 0
fi

mkdir -p "$WEB" "$USERDATA" "$ENV_DIR" "$UNIT_DIR"
install -m 0644 "$SRC/frontend/battery-control-guard-card.js" "$CARD"
install -m 0644 "$SRC/scripts/ha_status_export.py" "$EXPORTER"
install -m 0644 "$SRC/systemd/user/battery-control-guard-ha-export.service" "$SERVICE"
install -m 0644 "$SRC/systemd/user/battery-control-guard-ha-export.timer" "$TIMER"
printf 'BCG_HA_PUBLIC_DIR=%s\n' "$WEB" > "$ENVFILE"
chmod 0600 "$ENVFILE"
echo "Dashboard frontend installed in: $CARD"
echo "Optional exporter and systemd user timer installed but NOT activated."
echo "Add /local/guard/battery-control-guard-card.js as Lovelace module resource."
echo "When ready: systemctl --user daemon-reload"
echo "Then: systemctl --user enable --now battery-control-guard-ha-export.timer"
echo "See docs/HOME-ASSISTANT.md for the entity mapping, security and limitations."