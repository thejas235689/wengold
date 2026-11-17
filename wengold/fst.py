"""Bounded local FST conversion without any shell or unbounded output buffer."""
from __future__ import annotations

import os
from pathlib import Path
import selectors
import shutil
import subprocess
from time import monotonic


def to_vcd(path: Path, max_bytes: int, timeout: float = 8) -> bytes:
    converter = shutil.which("fst2vcd")
    if not converter:
        raise ValueError("FST needs GTKWave's fst2vcd on PATH")
    data = bytearray()
    deadline = monotonic() + timeout
    with subprocess.Popen([converter, "-f", str(path)], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
        try:
            with selectors.DefaultSelector() as reader:
                reader.register(child.stdout, selectors.EVENT_READ)
                while True:
                    left = deadline - monotonic()
                    if left <= 0 or not reader.select(left):
                        raise ValueError("FST conversion timed out")
                    chunk = os.read(child.stdout.fileno(), min(65536, max_bytes + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise ValueError("Expanded FST exceeds the 8 MiB viewer limit")
            if child.wait(timeout=max(0.01, deadline - monotonic())) != 0:
                raise ValueError("fst2vcd could not decode this FST")
        except subprocess.TimeoutExpired as exc:
            raise ValueError("FST conversion timed out") from exc
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    if b"$enddefinitions" not in data:
        raise ValueError("fst2vcd did not produce a VCD trace")
    return bytes(data)
