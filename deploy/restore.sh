#!/usr/bin/env bash
set -euo pipefail

: "${GEP_RESTORE_DIR:?Set GEP_RESTORE_DIR to a fresh runtime directory}"
if [[ "${GEP_RESTORE_CONFIRM:-}" != "restore-runtime" ]]; then
  echo "set GEP_RESTORE_CONFIRM=restore-runtime to restore" >&2
  exit 1
fi
archive="${1:?Usage: restore.sh BACKUP_DIRECTORY}"
if [[ ! -f "$archive/tasks.sqlite3" || ! -f "$archive/tasks.sqlite3.sha256" ]]; then
  echo "backup does not contain a database and checksum" >&2
  exit 1
fi
if [[ -e "$GEP_RESTORE_DIR" ]] && [[ -n "$(find "$GEP_RESTORE_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "restore directory must be empty: $GEP_RESTORE_DIR" >&2
  exit 1
fi
mkdir -p "$GEP_RESTORE_DIR"
(cd "$archive" && sha256sum -c tasks.sqlite3.sha256)
temporary="$GEP_RESTORE_DIR/.tasks.sqlite3.restore.$$"
cp "$archive/tasks.sqlite3" "$temporary"
mv "$temporary" "$GEP_RESTORE_DIR/tasks.sqlite3"
