#!/usr/bin/env bash
set -euo pipefail

if (( $# != 3 )); then
  echo 'usage: stage-release.sh RUNTIME_PATH FLAKE_LOCK OUTPUT_DIR' >&2
  exit 2
fi

runtime=$(readlink -f "$1")
lock=$2
output=$3
mkdir -p "$output"
revision=$(jq -r '.nodes.trynix.locked.rev' "$lock")
printf 'github:fzakaria/trynix/%s#native-qemu\n' "$revision" > "$output/qemu-source.txt"
tar -C "$runtime" -cf - guest vm.state qemu-path | zstd -T0 -q -f -o "$output/activity-vm-qemu-tcg.tar.zst"
(
  cd "$output"
  sha256sum qemu-source.txt activity-vm-qemu-tcg.tar.zst > SHA256SUMS
)
