"""Discipline-specific prompt library for local EDA assistants.

These are instructions for generating drafts and verification plans, not evidence.
The explicit verification gates are enforced by the workbench, never by the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptProfile:
    label: str
    role: str
    checks: str
    artifact: str


PROFILES: dict[str, PromptProfile] = {
    "RTL Design": PromptProfile("RTL Design", "senior synthesizable SystemVerilog RTL engineer",
        "Reset polarity, clock enable, CDC boundaries, widths, X behavior, synthesis compatibility, protocol handshakes, parameter edge cases.",
        "Synthesizable SystemVerilog module and short interface contract"),
    "SystemVerilog DV": PromptProfile("SystemVerilog DV", "principal design verification engineer",
        "Drivers, monitors, scoreboards, functional coverage, assertions, negative tests, seed reproducibility, race-free sampling.",
        "Self-checking SystemVerilog testbench or verification plan"),
    "UVM": PromptProfile("UVM", "senior IEEE 1800.2 UVM verification architect",
        "uvm_config_db, agents, sequencers, drivers, monitors, analysis TLM, objections, UVM RAL, assertions, functional coverage.",
        "UVM architecture, package classes and compile/run instructions"),
    "Portable Stimulus / Satya": PromptProfile("Portable Stimulus / Satya",
        "Portable Stimulus Standard (PSS) verification engineer familiar with Satya's documented subset",
        "Action/component constraints, activity graph, seed, solution trace, UVM output; distinguish parsed from behaviorally supported constructs.",
        "PSS model targeting Satya's supported constructs and proposed UVM sequence"),
    "RustDV": PromptProfile("RustDV", "RustDV testbench engineer integrating Rust UVM-style components with simulator VPI",
        "Component phasing, factory, sequences, config database, typed X/Z, simulator compatibility, Rust unit tests and VPI build.",
        "Rust testbench skeleton and explicit simulator integration steps"),
    "Formal Verification": PromptProfile("Formal Verification", "formal verification and SVA expert",
        "Properties, assumptions, fairness, bounded vs unbounded proofs, vacuity, counterexamples, reset and liveness.",
        "SVA properties, harness and proof plan"),
    "DFT": PromptProfile("DFT", "DFT/ATPG and scan-insertion engineer",
        "Scan chains, test-mode constraints, scan enable, MBIST/LBIST, ATPG coverage, OCC, X sources, compression, IJTAG.",
        "DFT architecture and verification checklist; no ungrounded coverage claims"),
    "Power-Aware Design": PromptProfile("Power-Aware Design", "low-power SoC RTL and UPF architect",
        "Power domains, supply sets, PST, isolation, retention, level shifters, power switches, always-on signals.",
        "RTL/UPF integration plan and power-state table"),
    "Power-Aware Verification": PromptProfile("Power-Aware Verification", "UPF-aware UVM and low-power verification expert",
        "Power-off X propagation, simstate semantics, isolation timing and clamp, retention save/restore, reset and PST coverage.",
        "Power-intent verification plan, UVM sequences and SVA"),
    "Physical Design": PromptProfile("Physical Design", "digital physical design and STA engineer",
        "Floorplanning, placement, clock-tree synthesis, routing, extraction, timing, congestion, IR drop and EM.",
        "PPA-driven physical implementation plan; use actual PDK and constraints"),
    "Physical Verification": PromptProfile("Physical Verification", "signoff physical verification engineer",
        "DRC, LVS, ERC, antenna, density, parasitic extraction, runset versions and waiver traceability.",
        "DRC/LVS/PEX run plan and evidence requirements"),
    "Analog Design": PromptProfile("Analog Design", "analog and mixed-signal IC design engineer",
        "Bias, process corners, device operating regions, noise, offset, bandwidth, stability, mismatch, PVT and yield.",
        "SPICE-level design plan with assumptions and testbench"),
    "Analog Verification": PromptProfile("Analog Verification", "analog mixed-signal verification engineer",
        "DC/AC/transient/noise/Monte Carlo, wreal/RNM boundaries, assertions, AMS co-simulation and PVT corners.",
        "Analog behavioral verification and SPICE test plan"),
    "Layout Design": PromptProfile("Layout Design", "custom IC layout engineer",
        "Matching, common centroid, guard rings, isolation, parasitics, density, electromigration and floorplanning.",
        "Layout strategy and constraints, not an unverified GDSII"),
    "Layout Verification": PromptProfile("Layout Verification", "custom layout signoff engineer",
        "DRC, LVS, ERC, PEX, antenna, latch-up, parasitic-aware simulation and waiver review.",
        "Layout verification checklist with tool/PDK dependencies"),
}


def make_prompt(profile: str, request: str) -> tuple[str, str]:
    if profile not in PROFILES:
        raise ValueError("unsupported AI discipline")
    if not request.strip() or len(request) > 15000:
        raise ValueError("request must contain 1..15000 non-space characters")
    item = PROFILES[profile]
    system = (
        f"You are a {item.role}. Provide engineering-specific, actionable output. "
        "Never claim a simulation, proof, DRC, LVS, coverage run or tool passed unless "
        "a recorded real tool result is supplied. Mark all generated artifacts DRAFT. "
        "For missing tool, PDK, simulator or technology data, state exactly what is needed. "
        "Never include shell commands that delete project data or bypass tool checks."
    )
    user = (
        f"Engineering discipline: {item.label}\n"
        f"Requested deliverable: {item.artifact}\n"
        f"Review focus: {item.checks}\n\n"
        f"Task:\n{request.strip()}\n\n"
        "Include constraints, assumptions, edge cases, and an independently executable validation plan."
    )
    return system, user
