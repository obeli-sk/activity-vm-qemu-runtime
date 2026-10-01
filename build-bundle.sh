#!/usr/bin/env bash
set -euo pipefail

if (( $# < 6 || $# > 7 )); then
  echo 'usage: build-bundle.sh QEMU_PATH KERNEL_PATH ROOTFS_ISO BIOS_DIR SETTIME_PATH OUTPUT_DIR [tcg|kvm]' >&2
  exit 2
fi

qemu=$1
kernel=$2
rootfs=$3
bios_dir=$4
settime=$5
output=$6
accel=${7:-tcg}
if [[ "$accel" != tcg && "$accel" != kvm ]]; then
  echo "unsupported accelerator: $accel" >&2
  exit 2
fi
if ! "$qemu" -accel help | grep -qx "$accel"; then
  echo "QEMU binary does not support the $accel accelerator: $qemu" >&2
  exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$output/guest"
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
bsdtar -C "$root" -xf "$rootfs"
cp "$source_dir/init" "$root/init"
chmod 755 "$root/init"
bsdtar -xOf "$bios_dir/initramfs.cpio.gz" bin/reseed > "$root/bin/reseed"
chmod 755 "$root/bin/reseed"
install -m 755 "$settime" "$root/bin/settime"
mkdir -p "$root/share"
# Processes without CAP_DAC_OVERRIDE (e.g. Chromium's children) must traverse / and write /tmp.
chmod 755 "$root"
chmod 1777 "$root/tmp"
(
  cd "$root"
  bsdtar --format=newc --uid 0 --gid 0 -cf - . | gzip -1 > "$output/guest/initramfs.cpio.gz"
)
cp -f "$kernel" "$output/guest/bzImage"
cp -f "$bios_dir"/*.bin "$output/guest/"
cp "$source_dir/machine.json" "$output/guest/machine.json"
if [[ "$accel" == kvm ]]; then
  sed -i 's/tcg,tb-size=500/kvm/' "$output/guest/machine.json"
fi
printf '%s\n' "$qemu" > "$output/qemu-path"
qemu_version=$("$qemu" --version | sed -n '1s/^QEMU emulator version //p')
test -n "$qemu_version"
printf '%s\n' "$qemu_version" > "$output/qemu-version.txt"
