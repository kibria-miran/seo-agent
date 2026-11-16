#!/bin/sh
# Weekly SEO GROWTH AGENT run (Phase 8).
#
#   seo-agent doctor  -> local checks (no network)
#   seo-agent run     -> polite live audit of the profile domain (network!)
#
# The default path is deterministic and needs no API keys; the live crawl
# honours robots.txt, a 2 s per-host delay and an honest user agent. Override
# the site profile with SEO_AGENT_SITE=/path/to/site.json.
#
# Cron (Monday 06:00):
#   0 6 * * 1 /opt/seo-agent/scripts/weekly.sh
# systemd: see README.md for the unit and timer.

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SITE=${SEO_AGENT_SITE:-"$PROJECT_DIR/profiles/site.json"}
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

{
    printf '%s doctor\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    "$PROJECT_DIR/.venv/bin/python" -m src.cli doctor --site "$SITE"

    printf '%s run\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    "$PROJECT_DIR/.venv/bin/python" -m src.cli run --site "$SITE" --no-llm
} >> "$LOG_DIR/weekly.log" 2>&1

printf 'seo-agent weekly run complete; see %s\n' "$LOG_DIR/weekly.log"
