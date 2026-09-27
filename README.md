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

The smoke test restores the snapshot, mounts the 9p mailbox, runs `/bin/echo`
in the guest, and checks its output. The Nix output contains `guest/`,
`vm.state`, and `qemu-path`. The path names the exact QEMU build used to create
the snapshot. Obelisk cannot safely restore it with a different QEMU build.

To use this output with the native backend in Obelisk:

```sh
export OBELISK_UNSTABLE_ACTIVITY_VM=qemu_native
export OBELISK_NATIVE_QEMU_BUNDLE=$(readlink -f result)
```

The backend currently supports Linux x86_64. macOS and Linux ARM builds are
future work, even though QEMU TCG can emulate x86_64 on those hosts.

## Release artifact

The GitHub Actions workflow builds and smoke tests the TCG bundle on every PR
and push. It uploads a compressed bundle plus the pinned TryNix QEMU source
reference. Version tags, or a manual workflow run with `push`, also publish it
to `docker.io/getobelisk/activity-vm-qemu-runtime` using ORAS. Docker Hub
publishing requires `DOCKER_HUB_USERNAME` and `DOCKER_HUB_TOKEN` secrets.

The OCI artifact carries the guest and snapshot. Installation requires Nix to
fetch the matching QEMU from the pinned TryNix source. The installer checks its
store path against the bundle before reporting success:

```sh
oras pull docker.io/getobelisk/activity-vm-qemu-runtime:v1
nix develop -c bash scripts/install-release.sh . /opt/obelisk/activity-vm-qemu-tcg
```

For a local release candidate, use:

```sh
nix develop -c bash scripts/stage-release.sh result flake.lock builds
nix develop -c bash scripts/install-release.sh builds /tmp/obelisk-qemu-installed
nix develop -c python3 scripts/smoke-test.py /tmp/obelisk-qemu-installed
```

## KVM development build

The KVM profile uses the pinned Nixpkgs QEMU and makes a separate snapshot on
a machine whose user can write `/dev/kvm`:

```sh
nix develop -c bash build-local.sh /tmp/obelisk-qemu-kvm kvm
```

KVM is not published by the TCG workflow. It needs its own KVM-capable runner
and artifact test before release. The two snapshots are never interchangeable.

## Inputs

The flake locks TryNix's QEMU and site, the Bochs runtime's Linux kernel and
rootfs, and Nixpkgs for the build tools and optional KVM QEMU. Obelisk's native
QEMU runner and activity launcher remain in the Obelisk repository.
