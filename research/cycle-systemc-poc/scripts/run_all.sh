#!/usr/bin/env bash
set -Eeuo pipefail

poc_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_root="${1:?用法: run_all.sh WORK_DIR}"
mkdir -p "${work_root}"

cmake -S "${poc_root}" -B "${work_root}/host-build" \
  -DBUILD_SYSTEMC_POC=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build "${work_root}/host-build" --parallel
ctest --test-dir "${work_root}/host-build" --output-on-failure
"${work_root}/host-build/model_benchmark" >"${work_root}/benchmark.csv"

# CIRCT 缺失会返回 2；保留报告并让总流程如实失败。
python3 "${poc_root}/tools/run_feature_ladder.py" \
  --work "${work_root}/circt"

