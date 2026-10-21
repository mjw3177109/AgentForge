#!/usr/bin/env bash
# V2.4 fresh-VM unit STAGING ONLY. Does not start/enable services.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE="$ROOT/deploy/v07/agentforge-worker.service"
TIMER="$ROOT/deploy/v07/agentforge-worker.timer"
TARGET="/etc/systemd/system"
case "${1:-}" in
  --help|-h)
    echo "Usage: sudo bash deploy/v24/stage_units.sh --stage-reviewed-units"
    echo "Fresh dedicated Linux VM only. Installs disabled systemd files, never enables/starts."
    exit 0 ;;
  --stage-reviewed-units) ;;
  *)
    echo "Refusing changes: explicitly pass --stage-reviewed-units after VM review" >&2
    exit 2 ;;
esac
[[ "$(id -u)" -eq 0 ]] || { echo "Run as root on a dedicated reviewed VM" >&2; exit 2; }
[[ -d /run/systemd/system ]] || { echo "systemd system manager required" >&2; exit 2; }
[[ -x /usr/bin/systemctl ]] || { echo "systemctl required" >&2; exit 2; }
[[ -x /usr/bin/systemd-analyze ]] || { echo "systemd-analyze required" >&2; exit 2; }
[[ -f "$SERVICE" && -f "$TIMER" ]] || { echo "Reviewed unit files missing" >&2; exit 2; }
python3 "$ROOT/scripts/check_django_v23_systemd.py"
if systemctl is-active --quiet agentforge-worker.service ||
   systemctl is-active --quiet agentforge-worker.timer; then
  echo "Existing Worker service/timer is active; refusing installation" >&2
  exit 2
fi
# Do not overwrite existing unit files, symlinks or operator overrides.
for name in agentforge-worker.service agentforge-worker.timer; do
  [[ ! -e "$TARGET/$name" && ! -L "$TARGET/$name" ]] || {
    echo "A Worker unit is already installed. Manual review required." >&2; exit 2;
  }
  [[ ! -d "$TARGET/$name.d" ]] || {
    echo "An unreviewed systemd drop-in exists" >&2; exit 2;
  }
done
systemd-analyze verify "$SERVICE" "$TIMER"
install -o root -g root -m 0644 "$SERVICE" "$TARGET/agentforge-worker.service"
install -o root -g root -m 0644 "$TIMER" "$TARGET/agentforge-worker.timer"
systemctl daemon-reload
# This must still prove that both units are installed but OFF.
python3 "$ROOT/scripts/audit_django_v24_systemd_host.py"
echo "Staged for operator review ONLY. Service inactive, timer disabled."
echo "No DB migrations, no service start/enable, no DeepSeek API calls."
