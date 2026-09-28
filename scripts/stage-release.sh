#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo 'usage: stage-release.sh RUNTIME_PATH FLAKE_LOCK OUTPUT_DIR [tcg|kvm]' >&2
  exit 2
fi

runtime=$(readlink -f "$1")
lock=$2
output=$3
accel=$4
if [[ "$accel" != tcg && "$accel" != kvm ]]; then
  echo "unsupported accelerator: $accel" >&2
  exit 2
fi
if ! jq -e --arg accel "$accel" \
  '.args as $args | ($args | index("-accel")) as $i | $i != null and ($args[$i + 1] | split(",")[0] == $accel)' \
  "$runtime/guest/machine.json" > /dev/null; then
  echo "runtime does not use $accel acceleration" >&2
  exit 1
fi
mkdir -p "$output"
nixpkgs_node=$(jq -er '.nodes.root.inputs.nixpkgs' "$lock")
revision=$(jq -er --arg node "$nixpkgs_node" '.nodes[$node].locked.rev' "$lock")
printf 'github:NixOS/nixpkgs/%s#qemu\n' "$revision" > "$output/qemu-source.txt"
cp "$runtime/qemu-version.txt" "$output/qemu-version.txt"
tar -C "$runtime" -cf - guest vm.state qemu-path qemu-version.txt | zstd -T0 -q -f -o "$output/activity-vm-qemu-$accel.tar.zst"
(
  cd "$output"
  sha256sum qemu-source.txt qemu-version.txt "activity-vm-qemu-$accel.tar.zst" > SHA256SUMS
)
