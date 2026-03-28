#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

run_step() {
  echo
  echo "==> $*"
  "$@"
}

cd "${REPO_ROOT}"

run_step "${SCRIPT_DIR}/build_binary_glibc217.sh"
run_step "${REPO_ROOT}/dist/alred" --version
run_step "${REPO_ROOT}/dist/alred" --help
run_step "${SCRIPT_DIR}/prepare_release_artifacts.sh"

run_step "${SCRIPT_DIR}/build_binary_glibc228.sh"
run_step "${SCRIPT_DIR}/prepare_release_artifacts.sh" dist/alred alred-linux-x86_64-glibc228

run_step "${SCRIPT_DIR}/build_binary_glibc234.sh"
run_step "${SCRIPT_DIR}/prepare_release_artifacts.sh" dist/alred alred-linux-x86_64-glibc234

echo
echo "completed Linux x86_64 release artifact build flow"
