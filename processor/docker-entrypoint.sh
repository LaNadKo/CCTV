#!/bin/sh
set -eu

mkdir -p \
  "${PROCESSOR_RUNTIME_DIR:-/app/processor-runtime}" \
  "${RECORDINGS_DIR:-/app/media/recordings}" \
  "${SNAPSHOTS_DIR:-/app/media/snapshots}"

exec "$@"
