# Weekly data refresh on the JSA droplet

`deploy/run_refresh.sh` rebuilds `data/*.csv` and pushes them to this repo; Streamlit Cloud
then redeploys. It follows the other droplet apps: a git clone in `/opt`, a venv, and one
crontab line through `/opt/alerting/cron-alert` (emails on failure).

## Install (done 2026-10-27)

    git clone https://github.com/JSA-Dashboards/canada-crop-conditions.git /opt/canada-crop-conditions
    cd /opt/canada-crop-conditions
    python3 -m venv .venv && .venv/bin/pip install -r deploy/requirements-droplet.txt
    chmod +x deploy/run_refresh.sh

Push uses the droplet's existing `~/.git-credentials` (credential.helper store).

## Cron (America/Chicago)

    # Canada crop conditions data: Alberta/Saskatchewan/Manitoba weekly reports post by Friday; Monday is the catch-up (re-runs are idempotent, no diff = no push)
    30 18 * * 5 /opt/alerting/cron-alert "Canada crop data refresh" "/opt/canada-crop-conditions/logs/refresh_*.log" /opt/canada-crop-conditions/deploy/run_refresh.sh
    30 7 * * 1  /opt/alerting/cron-alert "Canada crop data refresh" "/opt/canada-crop-conditions/logs/refresh_*.log" /opt/canada-crop-conditions/deploy/run_refresh.sh

Healthchecks.io: the first ping creates the check `canada-crop-data-refresh` with a 1-day
default period, which false-alarms on the days between runs. Set its schedule by hand
(`30 18 * * 5` and `30 7 * * 1` need two checks or one check with a weekly period and 3-day grace).

## Notes

- Without `pdftotext` (poppler) on the box the Saskatchewan parser falls back to pdfplumber on
  every page: about 30 s per report, fine for one or two new reports a week.
- A new Saskatchewan season gets a new product id; `build_data.sk_current_product()` finds it
  from the landing page, so nothing needs editing in January.
- Manual run: `/opt/canada-crop-conditions/deploy/run_refresh.sh`; logs in `logs/`.
