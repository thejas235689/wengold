"""Run the Wengold SoC preview formal suite using Yosys, yosys-smtbmc and Z3."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

DEPTH = 16
HERE = Path(__file__).resolve().parent
BASELINE = "CPU_FIRST = 1'b1"
RTL = {
    "arbiter": ["arbiter"],
    "dma": ["arbiter", "dma"],
    "memory": ["memory"],
    "subsystem": ["arbiter", "dma", "memory", "subsystem"],
}
# Expected failure is identified by assertion name, not a nonzero tool exit.
JOBS = {
    "arbiter_cpu_first": ("arbiter", False, (), ("bmc", "induction", "cover"), None),
    "arbiter_dma_first": ("arbiter", True, ("EXPECT_DMA_FIRST",),
                          ("bmc", "induction", "cover"), None),
    "dma_cpu_first": ("dma", False, (), ("bmc", "induction", "cover"), None),
    "dma_dma_first": ("dma", True, (), ("bmc", "induction", "cover"), None),
    "memory": ("memory", False, (), ("bmc", "induction", "cover"), None),
    "subsystem_cpu_first": ("subsystem", False, (), ("bmc", "induction", "cover"), None),
    "subsystem_dma_first": ("subsystem", True, (), ("bmc", "induction", "cover"), None),
    "subsystem_misrouted_address": ("subsystem", False, ("MISROUTE_DMA_ADDR",),
                                   ("bmc",), "write_address_matches_owner"),
    "subsystem_corrupted_payload": ("subsystem", False, ("CORRUPT_DMA_PAYLOAD",),
                                    ("bmc",), "write_payload_matches_owner"),
    "subsystem_dropped_write": ("subsystem", False, ("DROP_WRITE",),
                                ("bmc",), "watched_subsystem_readback"),
    "old_priority_checker": ("arbiter", True, (), ("bmc",), "fresh_priority"),
    "bounded_service_cpu_first": ("arbiter", False, ("CHECK_BOUNDED_SERVICE",),
                                  ("bmc",), "four_ready_cycle_service"),
    "bounded_service_dma_first": ("arbiter", True,
                                  ("CHECK_BOUNDED_SERVICE", "EXPECT_DMA_FIRST"),
                                  ("bmc",), "four_ready_cycle_service"),
    "early_irq": ("dma", False, ("EARLY_IRQ",), ("bmc",), "irq_matches_second_acceptance"),
    "dropped_write": ("memory", False, ("DROP_WRITE",), ("bmc",),
                      "watched_word_matches_model"),
}


def capture(argv, cwd, filename):
    try:
        run = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=60)
        raw = run.stdout
        code = run.returncode
    except subprocess.TimeoutExpired as exc:
        raw = (exc.stdout or b"") + b"\nTimed out after 60 seconds\n"
        code = None
    except OSError as exc:
        raw = str(exc).encode()
        code = None
    (cwd / filename).write_bytes(raw)
    return code, raw.decode(errors="replace")


def verify(output):
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "inputs"
    (snapshot / "formal").mkdir(parents=True)
    shutil.copytree(HERE.parent / "rtl", snapshot / "rtl")
    for source in [*HERE.glob("*_formal.sv"), HERE / "run.py"]:
        shutil.copy2(source, snapshot / "formal")
    inputs = {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(snapshot.rglob("*")) if p.is_file()}
    tools = {}
    available = True
    for cmd, args in (("yosys", ["-V"]), ("yosys-smtbmc", ["--help"]),
                      ("z3", ["--version"])):
        code, message = capture([cmd, *args], output, f"{cmd}-version.log")
        tools[cmd] = message.splitlines()[0].strip() if message else ""
        # smtbmc --help can exit nonzero. Its usage must still be available.
        available &= ("yosys-smtbmc [options]" in message if cmd == "yosys-smtbmc"
                      else code == 0)
    jobs = {}
    for name, (kind, alternate, defines, modes, expected) in JOBS.items():
        if not available:
            jobs[name] = {"verdict": "tool_error", "reason": "toolchain unavailable"}
            continue
        cwd = output / name
        cwd.mkdir()
        sources = []
        for module in RTL[kind]:
            src = snapshot / "rtl" / f"{module}.sv"
            dst = cwd / src.name
            if module == "arbiter" and alternate:
                original = src.read_text(encoding="utf-8")
                if original.count(BASELINE) != 1:
                    raise ValueError("Cannot derive DMA-first variant from this baseline")
                dst.write_text(original.replace(BASELINE, "CPU_FIRST = 1'b0"), encoding="utf-8")
            else:
                shutil.copy2(src, dst)
            sources.append(dst.name)
        top = f"{kind}_formal"
        shutil.copy2(snapshot / "formal" / f"{top}.sv", cwd)
        sources.append(f"{top}.sv")
        flags = " ".join(f"-D{define}" for define in defines)
        yosys_script = (f"read_verilog -formal -sv {flags} {' '.join(sources)}\n"
                        f"prep -top {top}\nmemory_map\nopt\nasync2sync\ndffunmap\n"
                        "write_smt2 -wires design.smt2\n")
        (cwd / "design.ys").write_text(yosys_script, encoding="utf-8")
        build = ["yosys", "-Q", "-T", "-s", "design.ys"]
        code, _ = capture(build, cwd, "yosys.log")
        result = {"verdict": "tool_error", "build": build, "expected_assertion": expected,
                  "script": "design.ys", "inputs": {p: hashlib.sha256((cwd / p).read_bytes()).hexdigest()
                             for p in sources}, "checks": {}}
        if code == 0:
            for mode in modes:
                args = ["yosys-smtbmc", "-s", "z3", "-t", str(DEPTH), "--presat"]
                args += {"bmc": [], "induction": ["-i"], "cover": ["-c"]}[mode]
                trace = f"{mode}-%" if mode == "cover" else mode
                args += ["--dump-vcd", f"{trace}.vcd", "design.smt2"]
                code, log = capture(args, cwd, f"{mode}.log")
                failures = [line.strip() for line in log.splitlines()
                            if "Assert failed in " in line]
                if code == 0 and "Status: PASSED" in log and (
                        mode != "induction" or "Temporal induction successful" in log):
                    status = "passed"
                elif code == 1 and "Status: FAILED" in log:
                    status = "failed"
                else:
                    status = "tool_error"
                result["checks"][mode] = {
                    "status": status, "argv": args, "log": f"{mode}.log",
                    "failures": failures,
                    "traces": sorted(p.name for p in cwd.glob(f"{mode}*.vcd")),
                }
            checks = result["checks"]
            if expected:
                check = checks["bmc"]
                if (check["status"] == "failed" and check["failures"]
                        and all(line.endswith(f": {expected}") for line in check["failures"])
                        and (cwd / "bmc.vcd").is_file()):
                    result["verdict"] = "expected_counterexample"
                elif check["status"] != "tool_error":
                    result["verdict"] = "unexpected_result"
            elif all(checks[m]["status"] == "passed" for m in modes):
                result["verdict"] = "proved_and_covered"
            elif all(checks[m]["status"] != "tool_error" for m in modes):
                result["verdict"] = (
                    "unexpected_result" if checks["bmc"]["status"] == "failed"
                    else "proof_or_cover_not_established"
                )
        jobs[name] = result

    ok = all(job["verdict"] in {"proved_and_covered", "expected_counterexample"}
             for job in jobs.values())
    report = {"status": "suite_matched_expectations" if ok else "suite_not_verified",
              "scope": "preview arbiter, DMA, memory and integrated connectivity, not SoC signoff",
              "depth": DEPTH, "tools": tools, "inputs": inputs, "jobs": jobs}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new evidence directory")
    output = parser.parse_args().output
    report = verify(output)
    for name, job in report["jobs"].items():
        print(f"{name}: {job['verdict']}")
    print(output / "report.json")
    raise SystemExit(report["status"] != "suite_matched_expectations")
