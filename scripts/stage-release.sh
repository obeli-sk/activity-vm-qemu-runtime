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
nixpkgs_node=$(jq -er '.nodes.root.inputs.nixpkgs' "$lock")
revision=$(jq -er --arg node "$nixpkgs_node" '.nodes[$node].locked.rev' "$lock")
printf 'github:NixOS/nixpkgs/%s#qemu\n' "$revision" > "$output/qemu-source.txt"
cp "$runtime/qemu-version.txt" "$output/qemu-version.txt"
tar -C "$runtime" -cf - guest vm.state qemu-path qemu-version.txt | zstd -T0 -q -f -o "$output/activity-vm-qemu-tcg.tar.zst"
(
  cd "$output"
  sha256sum qemu-source.txt qemu-version.txt activity-vm-qemu-tcg.tar.zst > SHA256SUMS
)
