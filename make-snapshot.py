#!/usr/bin/env python3
"""Capture the native QEMU guest after Linux and nftables are ready."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time

READY = b"obelisk-native-qemu: ready for snapshot"


def qmp(sock, command, **arguments):
    request = {"execute": command}
    if arguments:
        request["arguments"] = arguments
    sock.sendall(json.dumps(request).encode() + b"\n")
    buffer = b""
    while True:
        buffer += sock.recv(65536)
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip():
                reply = json.loads(line)
                if "return" in reply or "error" in reply:
                    if "error" in reply:
                        raise RuntimeError(reply["error"])
                    return reply["return"]


def main(bundle):
    guest = os.path.join(bundle, "guest")
    qemu = open(os.path.join(bundle, "qemu-path")).read().strip()
    vhost_vsock = open(os.path.join(bundle, "vhost-vsock-path")).read().strip()
    machine = json.load(open(os.path.join(guest, "machine.json")))
    with tempfile.TemporaryDirectory() as work:
        share = os.path.join(work, "share")
        queue = os.path.join(work, "queue")
        os.mkdir(share)
        os.mkdir(queue)
        image = os.path.join(work, "store.img")
        if "store_image_bytes" in machine:
            subprocess.run(["mkfs.erofs", "--all-root", "-T0", image, share],
                           check=True, stdout=subprocess.DEVNULL)
            os.truncate(image, machine["store_image_bytes"])
        serial = os.path.join(work, "serial.log")
        monitor = os.path.join(work, "qmp.sock")
        vhost = os.path.join(work, "vhost.sock")
        vsock = os.path.join(work, "vsock")
        backend = None
        if machine.get("mailbox_vsock"):
            backend = subprocess.Popen([vhost_vsock, "--guest-cid", "3",
                                        "--socket", vhost, "--uds-path", vsock],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 10
            while not os.path.exists(vhost):
                if backend.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"vsock backend did not start: {backend.stderr.read()!r}")
                time.sleep(0.01)
        args = [arg.format(pack=guest, share=share, queue=queue, image=image,
                           ram=machine["ram"], vhost=vhost)
                for arg in machine["args"]]
        with open(serial, "wb") as console:
            vm = subprocess.Popen([qemu, *args, "-qmp", f"unix:{monitor},server,nowait"],
                                  stdin=subprocess.PIPE, stdout=console,
                                  stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if READY in open(serial, "rb").read():
                    break
                if vm.poll() is not None:
                    raise RuntimeError(f"QEMU exited {vm.returncode}: {open(serial, 'rb').read()[-4000:]!r}")
                time.sleep(0.1)
            else:
                raise RuntimeError(f"guest did not become ready: {open(serial, 'rb').read()[-4000:]!r}")

            sock = socket.socket(socket.AF_UNIX)
            sock.connect(monitor)
            sock.recv(65536)
            qmp(sock, "qmp_capabilities")
            state = os.path.join(bundle, "vm.state")
            qmp(sock, "migrate", uri=f"file:{state}")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                status = qmp(sock, "query-migrate")["status"]
                if status == "completed":
                    break
                if status in ("failed", "cancelled"):
                    raise RuntimeError(f"migration {status}")
                time.sleep(0.1)
            else:
                raise RuntimeError("migration timed out")
            qmp(sock, "quit")
            print(f"snapshot: {state} ({os.path.getsize(state)} bytes)")
        finally:
            vm.kill()
            vm.wait()
            if backend is not None:
                backend.kill()
                backend.wait()


if __name__ == "__main__":
    main(sys.argv[1])
