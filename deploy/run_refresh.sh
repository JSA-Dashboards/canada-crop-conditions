#!/usr/bin/env bash
# run_refresh.sh: weekly data refresh for the Canada crop conditions app, run by cron
# on the JSA droplet through /opt/alerting/cron-alert (see deploy/DROPLET.md).
#
# It pulls this repo, rebuilds data/*.csv from the public sources (StatCan yields, NOAA
# satellite, Alberta, Saskatchewan and Manitoba weekly reports), then commits and pushes
# the CSVs so Streamlit Cloud redeploys with fresh data. Any failing build step aborts
# before the commit (set -e), so a half-refreshed dataset is never pushed.
#
# The whole body is a function and the script ends with `exit`: bash reads a script
# incrementally, and the `git pull` below can rewrite this very file mid-run.
set -euo pipefail

main() {
  local APP=/opt/canada-crop-conditions
  local PY="$APP/.venv/bin/python"
  local YEAR
  YEAR=$(date +%Y)

  mkdir -p "$APP/logs"
  exec >>"$APP/logs/refresh_$(date +%F).log" 2>&1
  echo "[$(date '+%F %T')] refresh start"

  # one run at a time; a second run exits quietly
  exec 9>/tmp/canada-crop-refresh.lock
  flock -n 9 || { echo "another refresh is running"; return 0; }

  cd "$APP"
  git pull --ff-only --quiet

  "$PY" -u build_data.py yields
  "$PY" -u build_data.py stocks
  "$PY" -u build_data.py vh
  "$PY" -u build_data.py ab "$YEAR"
  "$PY" -u build_data.py sk "$YEAR"
  "$PY" -u build_data.py mb "$YEAR"
  "$PY" -u build_data.py mxvh
  "$PY" -u build_data.py mxprod
  "$PY" -u build_data.py mxprog
  "$PY" -u build_data.py mxstates
  "$PY" -u build_data.py frvh
  "$PY" -u build_data.py frcereobs
  "$PY" -u build_data.py frmars
  "$PY" -u build_data.py fryields
  "$PY" -u build_data.py brvh
  "$PY" -u build_data.py brseries
  "$PY" -u build_data.py brprog

  git config user.email '275148418+koltenpostin93-blip@users.noreply.github.com'
  git config user.name 'JSA Droplet'
  git add data/*.csv
  if git diff --cached --quiet; then
    echo "[$(date '+%F %T')] no new data, nothing to push"
  else
    git commit -q -m "chore: refresh data $(date +%F)"
    git push -q origin main
    echo "[$(date '+%F %T')] pushed refreshed data"
  fi
  echo "[$(date '+%F %T')] refresh done"
}

main "$@"
exit
