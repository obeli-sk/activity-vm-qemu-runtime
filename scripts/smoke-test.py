#!/usr/bin/env python3
"""Restore a built bundle and run one guest shell command over 9p."""

import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time


def wait_until_running(monitor, vm):
    deadline = time.monotonic() + 15
    while not monitor.exists():
        if vm.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("QEMU did not start its QMP monitor")
        time.sleep(0.01)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(monitor))
        with connection.makefile("rwb") as stream:
            stream.readline()
            for command in ("qmp_capabilities", "query-status"):
                while True:
                    stream.write(json.dumps({"execute": command}).encode() + b"\n")
                    stream.flush()
                    reply = json.loads(stream.readline())
                    if "return" in reply:
                        if command != "query-status" or reply["return"]["status"] == "running":
                            break
                        time.sleep(0.01)
                    elif "error" in reply:
                        raise RuntimeError(reply["error"])


def main(bundle):
    bundle = pathlib.Path(bundle).resolve()
    guest = bundle / "guest"
    machine = json.loads((guest / "machine.json").read_text())
    qemu = (bundle / "qemu-path").read_text().strip()
    with tempfile.TemporaryDirectory() as work:
        work = pathlib.Path(work)
        share = work / "share"
        queue = work / "queue"
        share.mkdir()
        queue.mkdir()
        (queue / "run.sh").write_text("#!/bin/sh\n/bin/echo activity-vm-qemu-ready > /obelisk-activity-vm-http/smoke-result\n")
        args = [arg.format(pack=guest, share=share, queue=queue, ram=machine["ram"])
                for arg in machine["args"]]
        monitor = work / "qmp.sock"
        serial = work / "serial.log"
        console = serial.open("wb")
        vm = subprocess.Popen(
            [qemu, *args, "-incoming", f"file:{bundle / 'vm.state'}", "-qmp",
             f"unix:{monitor},server,nowait"],
            stdin=subprocess.PIPE,
            stdout=console,
            stderr=subprocess.PIPE,
        )
        console.close()
        try:
            wait_until_running(monitor, vm)
            vm.stdin.write(b"\n")
            vm.stdin.flush()
            result = queue / "smoke-result"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if result.exists():
                    actual = result.read_text().strip()
                    if actual != "activity-vm-qemu-ready":
                        raise RuntimeError(f"unexpected guest output: {actual!r}")
                    print(actual)
                    return
                if vm.poll() is not None:
                    raise RuntimeError(f"QEMU exited {vm.returncode}: {vm.stderr.read()[-4000:]!r}")
                time.sleep(0.05)
            raise RuntimeError("guest did not complete smoke command")
        finally:
            vm.kill()
            vm.wait()


if __name__ == "__main__":
    main(sys.argv[1])
