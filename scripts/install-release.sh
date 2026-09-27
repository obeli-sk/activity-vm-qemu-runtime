#!/usr/bin/env bash
set -euo pipefail

if (( $# != 2 )); then
  echo 'usage: install-release.sh RELEASE_DIR OUTPUT_DIR' >&2
  exit 2
fi

release=$1
output=$2
(
  cd "$release"
  sha256sum -c SHA256SUMS
)
qemu_source=$(cat "$release/qemu-source.txt")
qemu=$(nix build --accept-flake-config --no-link --print-out-paths "$qemu_source")
mkdir -p "$output"
zstd -dc "$release/activity-vm-qemu-tcg.tar.zst" | tar -C "$output" -xf -
expected=$(cat "$output/qemu-path")
if [[ "$expected" != "$qemu/bin/qemu-system-x86_64" ]]; then
  echo "QEMU path mismatch: expected $expected, got $qemu" >&2
  exit 1
fi
test -f "$output/vm.state"
printf '%s\n' "$output"
