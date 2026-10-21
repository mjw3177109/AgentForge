#!/usr/bin/env bash
# V2.4 fresh-VM unit STAGING ONLY. Does not start/enable services.
set -euo pipefail
umask 077
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
# A real installer must not race a second copy of itself.
command -v flock >/dev/null || { echo "flock is required" >&2; exit 2; }
exec 9>/run/lock/agentforge-v25-stage.lock
flock -n 9 || { echo "Another installer is running" >&2; exit 2; }
# A failed fresh installation rolls back ONLY exact files it created.
created_service=0
created_timer=0
finished=0
cleanup() {
  status=$?
  if [[ "$finished" -ne 1 ]]; then
    if [[ "$created_timer" -eq 1 && -f "$TARGET/agentforge-worker.timer" &&
          ! -L "$TARGET/agentforge-worker.timer" ]] &&
       cmp -s "$TIMER" "$TARGET/agentforge-worker.timer"; then
      rm -f -- "$TARGET/agentforge-worker.timer"
    fi
    if [[ "$created_service" -eq 1 && -f "$TARGET/agentforge-worker.service" &&
          ! -L "$TARGET/agentforge-worker.service" ]] &&
       cmp -s "$SERVICE" "$TARGET/agentforge-worker.service"; then
      rm -f -- "$TARGET/agentforge-worker.service"
    fi
    systemctl daemon-reload >/dev/null 2>&1 || true
    echo "Staging incomplete. Inspect leftover unit files manually before retry." >&2
  fi
  return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ -d /run/systemd/system ]] || { echo "systemd system manager required" >&2; exit 2; }
[[ -x /usr/bin/systemctl ]] || { echo "systemctl required" >&2; exit 2; }
[[ -x /usr/bin/systemd-analyze ]] || { echo "systemd-analyze required" >&2; exit 2; }
[[ -f "$SERVICE" && -f "$TIMER" ]] || { echo "Reviewed unit files missing" >&2; exit 2; }
python3 "$ROOT/scripts/check_django_v23_systemd.py"
# Read-only checks of the REAL VM identity, immutable source/venv and
# root-owned 0600 EnvironmentFile. Do not parse or print credentials.
python3 "$ROOT/scripts/check_django_v25_host.py"
if systemctl is-active --quiet agentforge-worker.service ||
   systemctl is-active --quiet agentforge-worker.timer ||
   systemctl is-enabled --quiet agentforge-worker.timer; then
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
created_service=1
install -o root -g root -m 0644 "$SERVICE" "$TARGET/agentforge-worker.service"
created_timer=1
install -o root -g root -m 0644 "$TIMER" "$TARGET/agentforge-worker.timer"
systemctl daemon-reload
# This must still prove that both units are installed but OFF.
python3 "$ROOT/scripts/audit_django_v24_systemd_host.py"
finished=1
echo "Staged for operator review ONLY. Service inactive, timer disabled."
echo "No DB migrations, no service start/enable, no DeepSeek API calls."
