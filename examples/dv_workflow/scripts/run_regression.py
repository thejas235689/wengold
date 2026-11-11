#!/usr/bin/env python3
"""Real Icarus run and observed coverage marker interchange for WENGOLD."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
results = root / "results"
results.mkdir(exist_ok=True)
iv = shutil.which("iverilog")
vvp = shutil.which("vvp")
if not iv or not vvp:
    print("ERROR: install iverilog and vvp first", file=sys.stderr)
    sys.exit(2)
exe = results / "counter4.vvp"
compile_result = subprocess.run(
    [iv, "-g2012", "-s", "counter4_tb", "-o", str(exe),
     str(root / "rtl/counter4.sv"), str(root / "tb/counter4_tb.sv")],
    capture_output=True, text=True, timeout=20, check=False)
if compile_result.returncode:
    print("COMPILE_FAIL", compile_result.stdout, compile_result.stderr,
          file=sys.stderr)
    sys.exit(3)
sim = subprocess.run([vvp, str(exe)], capture_output=True, text=True,
                     timeout=20, check=False)
output = sim.stdout + "\n" + sim.stderr
(results / "regression.log").write_text(output, encoding="utf-8")
if sim.returncode or "REGRESSION_PASS" not in output or any(
    token in output.upper() for token in ("ERROR", "FATAL", "FAIL")):
    print(output, file=sys.stderr)
    sys.exit(4)
observed = {line[len("COVER:"):].strip()
            for line in output.splitlines() if line.startswith("COVER:")}
bins = [{"name": name, "hits": int(name in observed)}
        for name in ("reset", "increment", "hold", "wraparound")]
(results / "coverage.json").write_text(
    json.dumps({"source": "observed simulation markers",
                "bins": bins}, indent=2) + "\n", encoding="utf-8")
print(output, end="")
print("MEASURED_BINS:", len(observed), "/ 4")
