# Native QEMU activity VM runtime

This repository builds the minimal Linux guest and migration snapshot for
Obelisk's native QEMU activity VM backend. The default artifact uses software
emulation (TCG), so building and running it does not require root or `/dev/kvm`.
The guest boots once during the build, configures loopback and nftables, and is
snapshotted before it mounts activity-specific 9p shares.

## Build and test

```sh
nix build
nix develop -c python3 scripts/smoke-test.py result
```

The smoke test restores the snapshot, plugs 1 GiB of guest RAM, mounts the 9p
mailbox, runs `/bin/echo` in the guest, and checks its output, the guest's RAM,
and the size of its root filesystem. The Nix output contains `guest/`,
`vm.state`, `qemu-path`, and `qemu-version.txt`. The path names the exact QEMU
build used to create the snapshot. Obelisk cannot safely restore it with a
different QEMU build.

To use this output with the native backend in Obelisk:

```sh
export OBELISK_UNSTABLE_ACTIVITY_VM=qemu-tcg
export OBELISK_NATIVE_QEMU_BUNDLE=$(readlink -f result)
```

The snapshot has 256 MiB of RAM and an empty 16 GiB `virtio-mem` device, described
by `hotplug` in `guest/machine.json`. Obelisk plugs an activity's extra RAM over
QMP after restoring the snapshot and before sending the wall clock, and `init`
then resizes the root filesystem to 90% of the enlarged RAM. The kernel is the
Bochs runtime's kernel with memory hotplug and `virtio-mem` enabled. The guest
boots with `rcupdate.rcu_expedited=1`; without it, the first plug after restore
waits about 0.5 s on KVM for an RCU grace period.

The backend currently supports Linux x86_64. macOS and Linux ARM builds are
future work, even though QEMU TCG can emulate x86_64 on those hosts.

## Release artifact

The GitHub Actions workflow builds and smoke tests separate TCG and KVM bundles
on every PR and push. It uploads both compressed bundles with the pinned Nixpkgs
QEMU source reference and QEMU version (currently 11.1.1). Run the `runtime`
workflow on `main` with a new `YYYY-MM-DD` tag (or `YYYY-MM-DD-N`) to publish them to
`docker.io/getobelisk/activity-vm-qemu-tcg-runtime` and
`docker.io/getobelisk/activity-vm-qemu-kvm-runtime` using ORAS. The workflow
opens an Obelisk PR containing both digest-pinned OCI references with no trailing
newlines, then creates the release tag in this repository. Publication requires
`DOCKER_HUB_USERNAME`, `DOCKER_HUB_TOKEN`, and `RUNTIME_TO_OBELISK_PR` secrets.

The OCI artifact carries the guest and snapshot. Installation requires Nix to
fetch the matching standard QEMU from pinned Nixpkgs. The installer checks its
store path against the bundle before reporting success:

```sh
oras pull docker.io/getobelisk/activity-vm-qemu-tcg-runtime:2026-09-28
nix develop -c bash scripts/install-release.sh . /opt/obelisk/activity-vm-qemu-tcg tcg
```

For a local release candidate, use:

```sh
nix develop -c bash scripts/stage-release.sh result flake.lock builds tcg
nix develop -c bash scripts/install-release.sh builds /tmp/obelisk-qemu-installed tcg
nix develop -c python3 scripts/smoke-test.py /tmp/obelisk-qemu-installed
```

## KVM development build

The KVM profile uses the same pinned Nixpkgs QEMU and makes a separate snapshot on
a machine whose user can write `/dev/kvm`:

```sh
nix develop -c bash build-local.sh /tmp/obelisk-qemu-kvm kvm
nix develop -c python3 scripts/smoke-test.py /tmp/obelisk-qemu-kvm
```

The workflow builds KVM outside the Nix sandbox on an x86_64 runner with writable
`/dev/kvm`, then installs and smoke tests the staged artifact before publishing.
The two snapshots are never interchangeable.
For a local Obelisk debug build, set `OBELISK_UNSTABLE_ACTIVITY_VM=qemu-kvm` and
`OBELISK_NATIVE_QEMU_BUNDLE=/tmp/obelisk-qemu-kvm`.

## Inputs

The flake locks Nixpkgs QEMU, the TryNix site, and the Bochs runtime's Linux
kernel and rootfs. Obelisk's native QEMU runner and activity launcher remain
in the Obelisk repository.
