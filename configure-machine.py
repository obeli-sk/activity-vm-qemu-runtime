#!/usr/bin/env python3
"""Select closure and mailbox devices for a local QEMU runtime bundle."""

import json
import sys


def replace_pair(args, option, value_prefix, old_length, replacement):
    for index in range(len(args) - 3):
        if args[index] == option and args[index + 1].startswith(value_prefix):
            args[index:index + old_length] = replacement
            return
    raise ValueError(f"missing device pair: {option} {value_prefix}")


path, store_mode, mailbox_mode = sys.argv[1:]
with open(path) as source:
    machine = json.load(source)
args = machine["args"]
if store_mode == "9p":
    del machine["store_image_bytes"]
    replace_pair(args, "-drive", "file={image}", 4, [
        "-fsdev", "local,id=store0,path={share},security_model=none,readonly=on,multidevs=remap",
        "-device", "virtio-9p-pci,fsdev=store0,mount_tag=store0,ioeventfd=off",
    ])
if mailbox_mode == "9p":
    del machine["mailbox_vsock"]
    replace_pair(args, "-chardev", "socket,id=vsock0", 2, [
        "-fsdev", "local,id=queue0,path={queue},security_model=none,multidevs=remap",
        "-device", "virtio-9p-pci,fsdev=queue0,mount_tag=queue0,ioeventfd=off",
    ])
with open(path, "w") as destination:
    json.dump(machine, destination, indent=2)
