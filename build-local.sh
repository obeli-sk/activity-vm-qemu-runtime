#!/usr/bin/env bash
set -euo pipefail

if (( $# < 1 || $# > 2 )); then
  echo 'usage: build-local.sh OUTPUT_DIR [tcg|kvm]' >&2
  exit 2
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
accel=${2:-tcg}
if [[ "$accel" != tcg && "$accel" != kvm ]]; then
  echo "unsupported accelerator: $accel" >&2
  exit 2
fi
for tool in bsdtar python3 gzip; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is required; run this script with nix develop -c bash" >&2
    exit 1
  fi
done
if [[ "$accel" == kvm && ! -w /dev/kvm ]]; then
  echo 'KVM requested but /dev/kvm is not writable by this user' >&2
  exit 1
fi

if [[ "$accel" == kvm ]]; then
  qemu=$(nix build --no-link --print-out-paths .#qemu-kvm)
else
  qemu=$(nix build --no-link --print-out-paths .#qemu-tcg)
fi
site=$(nix build --no-link --print-out-paths .#site)
kernel=$(nix build --no-link --print-out-paths .#kernel)
rootfs=$(nix build --no-link --print-out-paths .#rootfs)
settime=$(nix build --no-link --print-out-paths .#settime)
bash "$source_dir/build-bundle.sh" \
  "$qemu/bin/qemu-system-x86_64" \
  "$kernel/bzImage" \
  "$rootfs/rootfs.bin" \
  "$site/guest" \
  "$settime/bin/settime" \
  "$1" \
  "$accel"
python3 "$source_dir/make-snapshot.py" "$1"
