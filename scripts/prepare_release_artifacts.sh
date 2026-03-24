#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist"

INPUT_BINARY="${1:-${DIST_DIR}/alred}"
ARTIFACT_BASENAME="${2:-alred-linux-x86_64-glibc217}"
OUTPUT_BINARY="${DIST_DIR}/${ARTIFACT_BASENAME}"
OUTPUT_CHECKSUM="${OUTPUT_BINARY}.sha256"

if [[ ! -f "${INPUT_BINARY}" ]]; then
  echo "input binary not found: ${INPUT_BINARY}" >&2
  exit 1
fi

cp "${INPUT_BINARY}" "${OUTPUT_BINARY}"
sha256sum "${OUTPUT_BINARY}" > "${OUTPUT_CHECKSUM}"

echo "prepared artifact: ${OUTPUT_BINARY}"
echo "prepared checksum: ${OUTPUT_CHECKSUM}"
echo "artifact basename: ${ARTIFACT_BASENAME}"
