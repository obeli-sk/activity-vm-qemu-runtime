#!/usr/bin/env bash
set -euo pipefail

if (( $# != 3 )); then
  echo 'usage: install-release.sh RELEASE_DIR OUTPUT_DIR [tcg|kvm]' >&2
  exit 2
fi

release=$1
output=$2
accel=$3
if [[ "$accel" != tcg && "$accel" != kvm ]]; then
  echo "unsupported accelerator: $accel" >&2
  exit 2
fi
(
  cd "$release"
  sha256sum -c SHA256SUMS
)
qemu_source=$(cat "$release/qemu-source.txt")
qemu=$(nix build --accept-flake-config --no-link --print-out-paths "$qemu_source")
expected_version=$(cat "$release/qemu-version.txt")
actual_version=$("$qemu/bin/qemu-system-x86_64" --version | sed -n '1s/^QEMU emulator version //p')
if [[ "$actual_version" != "$expected_version" ]]; then
  echo "QEMU version mismatch: expected $expected_version, got $actual_version" >&2
  exit 1
fi
mkdir -p "$output"
zstd -dc "$release/activity-vm-qemu-$accel.tar.zst" | tar -C "$output" -xf -
if [[ "$(cat "$output/qemu-version.txt")" != "$expected_version" ]]; then
  echo "QEMU version in bundle does not match release metadata" >&2
  exit 1
fi
expected=$(cat "$output/qemu-path")
if [[ "$expected" != "$qemu/bin/qemu-system-x86_64" ]]; then
  echo "QEMU path mismatch: expected $expected, got $qemu" >&2
  exit 1
fi
test -f "$output/vm.state"
printf '%s\n' "$output"
