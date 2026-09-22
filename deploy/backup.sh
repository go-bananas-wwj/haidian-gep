#!/usr/bin/env bash
set -euo pipefail

: "${GEP_RUNTIME_DIR:?Set GEP_RUNTIME_DIR to the persistent runtime directory}"
: "${GEP_BACKUP_DIR:?Set GEP_BACKUP_DIR to an approved backup directory}"

database="$GEP_RUNTIME_DIR/tasks.sqlite3"
if [[ ! -f "$database" ]]; then
  echo "runtime database does not exist: $database" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$GEP_BACKUP_DIR/runtime-$timestamp"
suffix=0
while [[ -e "$archive" ]]; do
  suffix=$((suffix + 1))
  archive="$GEP_BACKUP_DIR/runtime-$timestamp-$suffix"
done
mkdir -p "$archive"

python3 - "$database" "$archive/tasks.sqlite3" <<'PY'
import sqlite3
import sys

source, target = sys.argv[1:]
with sqlite3.connect(source) as input_db, sqlite3.connect(target) as output_db:
    input_db.backup(output_db)
PY

(cd "$archive" && sha256sum tasks.sqlite3 > tasks.sqlite3.sha256)
printf '%s\n' "$archive"
