#!/usr/bin/env python3
"""Restore a built bundle, plug 1 GiB and one vCPU, and run one guest shell command."""

import json
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import time

PLUG_BYTES = 1 << 30
CPUS = 2


def qmp(stream, command, **arguments):
    request = {"execute": command}
    if arguments:
        request["arguments"] = arguments
    stream.write(json.dumps(request).encode() + b"\n")
    stream.flush()
    while True:
        reply = json.loads(stream.readline())
        if "return" in reply:
            return reply["return"]
        if "error" in reply:
            raise RuntimeError(reply["error"])


def restore_and_plug(monitor, vm, hotplug, mailbox_vsock):
    deadline = time.monotonic() + 15
    while not monitor.exists():
        if vm.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("QEMU did not start its QMP monitor")
        time.sleep(0.01)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(monitor))
        with connection.makefile("rwb") as stream:
            stream.readline()
            qmp(stream, "qmp_capabilities")
            while qmp(stream, "query-status")["status"] != "running":
                time.sleep(0.01)
            path = f"/machine/peripheral/{hotplug['device']}"
            qmp(stream, "qom-set", path=path, property="requested-size", value=PLUG_BYTES)
            deadline = time.monotonic() + 15
            while qmp(stream, "qom-get", path=path, property="size") != PLUG_BYTES:
                if time.monotonic() >= deadline:
                    raise RuntimeError("guest did not plug memory")
                time.sleep(0.01)
            free = [cpu for cpu in qmp(stream, "query-hotpluggable-cpus") if "qom-path" not in cpu]
            for index, cpu in enumerate(sorted(free, key=lambda cpu: cpu["props"]["socket-id"])[:CPUS - 1]):
                qmp(stream, "device_add", driver=cpu["type"], id=f"cpu{index + 1}", **cpu["props"])
            if mailbox_vsock:
                qmp(stream, "device_add", driver="vhost-user-vsock-pci",
                    chardev="vsock0", id="mailbox-vsock")


def read_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise RuntimeError("guest closed vsock mailbox")
        data.extend(chunk)
    return bytes(data)


def send_file(connection, name, data):
    encoded = name.encode()
    connection.sendall(struct.pack("<HQ", len(encoded), len(data)) + encoded + data)


def receive_file(connection):
    name_size, data_size = struct.unpack("<HQ", read_exact(connection, 10))
    name = read_exact(connection, name_size).decode()
    return name, read_exact(connection, data_size)


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
        image = work / "store.img"
        if "store_image_bytes" in machine:
            subprocess.run(["mkfs.erofs", "--all-root", "-T0", image, share],
                           check=True, stdout=subprocess.DEVNULL)
            with image.open("r+b") as image_file:
                image_file.truncate(machine["store_image_bytes"])
        # Rename so the host never observes the result file before it is written.
        run_script = (
            "#!/bin/sh\n"
            "/bin/echo activity-vm-qemu-ready $(/bin/date +%s)"
            " $(/bin/grep MemTotal /proc/meminfo | /bin/tr -s ' ' | /bin/cut -d ' ' -f 2)"
            " $(($(/bin/stat -f -c '%b * %S' /) / 1024))"
            " $(/bin/nproc)"
            " $(/bin/grep -m1 vendor_id /proc/cpuinfo | /bin/tr -d ' \\t' | /bin/cut -d : -f 2)"
            " $(/bin/cat /sys/devices/system/clocksource/clocksource0/current_clocksource)"
            " > /obelisk-activity-vm-http/smoke-result.tmp\n"
            "/bin/mv /obelisk-activity-vm-http/smoke-result.tmp /obelisk-activity-vm-http/smoke-result\n"
        )
        mailbox_vsock = machine.get("mailbox_vsock", False)
        listener = None
        backend = None
        vhost = work / "vhost.sock"
        vsock = work / "vsock"
        if mailbox_vsock:
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(f"{vsock}_1024")
            listener.listen(1)
            listener.settimeout(25)
            vhost_binary = (bundle / "vhost-vsock-path").read_text().strip()
            backend = subprocess.Popen([vhost_binary, "--guest-cid", "3", "--socket",
                                        str(vhost), "--uds-path", str(vsock)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 10
            while not vhost.exists():
                if backend.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError(f"vsock backend did not start: {backend.stderr.read()!r}")
                time.sleep(0.01)
        else:
            (queue / "run.sh").write_text(run_script)
        args = [arg.format(pack=guest, share=share, queue=queue, image=image,
                           ram=machine["ram"], vhost=vhost)
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
            restore_and_plug(monitor, vm, machine["hotplug"], mailbox_vsock)
            now = time.time_ns()
            vm.stdin.write(f"{now // 10**9}.{now % 10**9:09} {CPUS}\n".encode())
            vm.stdin.flush()
            result = queue / "smoke-result"
            if mailbox_vsock:
                connection, _ = listener.accept()
                connection.settimeout(20)
                send_file(connection, "run.sh", run_script.encode())
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if mailbox_vsock:
                    name, data = receive_file(connection)
                    if name == "smoke-result":
                        result.write_bytes(data)
                if result.exists():
                    actual = result.read_text().split()
                    if len(actual) != 7 or actual[0] != "activity-vm-qemu-ready":
                        raise RuntimeError(f"unexpected guest output: {actual!r}")
                    mem_kib, root_kib = int(actual[2]), int(actual[3])
                    if mem_kib < (PLUG_BYTES >> 10) or root_kib < (PLUG_BYTES >> 10):
                        raise RuntimeError(f"plugged memory missing: MemTotal {mem_kib} KiB, / {root_kib} KiB")
                    if int(actual[4]) != CPUS:
                        raise RuntimeError(f"guest has {actual[4]} vCPUs, expected {CPUS}")
                    # KVM exposes the build host's vendor unless it is pinned, and a non-Intel
                    # guest with hotplug slots distrusts its TSC and falls back to HPET.
                    if actual[5] != "GenuineIntel" or not actual[6].startswith("tsc"):
                        raise RuntimeError(f"guest CPU is {actual[5]} with clocksource {actual[6]}")
                    skew = int(actual[1]) - time.time()
                    if abs(skew) > 5:
                        raise RuntimeError(f"guest clock is off by {skew:.1f} s")
                    print(f"{actual[0]} (clock skew {skew:.1f} s, MemTotal {mem_kib >> 10} MiB, / {root_kib >> 10} MiB, {CPUS} vCPUs, {actual[5]}, {actual[6]})")
                    return
                if vm.poll() is not None:
                    raise RuntimeError(f"QEMU exited {vm.returncode}: {vm.stderr.read()[-4000:]!r}")
                time.sleep(0.05)
            raise RuntimeError(f"guest did not complete smoke command: {serial.read_text(errors='replace')[-4000:]}")
        finally:
            vm.kill()
            vm.wait()
            if backend is not None:
                backend.kill()
                backend.wait()
            if listener is not None:
                listener.close()


if __name__ == "__main__":
    main(sys.argv[1])
