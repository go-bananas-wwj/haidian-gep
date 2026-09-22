#!/usr/bin/env bash
set -euo pipefail

url="${GEP_HEALTH_URL:-http://127.0.0.1:9088/api/health}"
attempts="${GEP_HEALTH_ATTEMPTS:-12}"
delay="${GEP_HEALTH_DELAY_SECONDS:-2}"

if ! [[ "$attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "GEP_HEALTH_ATTEMPTS must be a positive integer" >&2
  exit 2
fi

for attempt in $(seq 1 "$attempts"); do
  if curl --fail --silent --show-error --max-time 5 "$url" >/dev/null; then
    printf 'healthy after attempt %s: %s\n' "$attempt" "$url"
    exit 0
  fi
  if [[ "$attempt" -lt "$attempts" ]]; then
    sleep "$delay"
  fi
done

echo "health check failed after $attempts attempts: $url" >&2
exit 1
