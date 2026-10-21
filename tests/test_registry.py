"""The registry must cover all three groups, exactly as the flow is organised."""
from wengold.tools.registry import TOOL_GROUPS, GROUP_TITLES, all_tools

EXPECTED = {
    "simulation": {"VCS", "Xcelium", "Questa", "Verilator", "Verdi", "SimVision",
                   "Verisium", "GTKWave", "cocotb", "UVM"},
    "formal": {"JasperGold", "VC Formal", "OneSpin", "ZeBu", "Palladium",
               "Veloce", "Vivado", "Quartus", "Yosys", "vManager"},
    "flow": {"Git", "GitHub", "GitLab", "Jira", "Slack", "Tcl", "Python", "Make"},
}


def test_groups_present():
    assert set(TOOL_GROUPS) == {"simulation", "formal", "flow"}
    assert GROUP_TITLES["simulation"] == "Simulation, debug and testbench"


def test_group_membership():
    for group, names in EXPECTED.items():
        have = {t.name for t in TOOL_GROUPS[group]}
        assert names <= have, f"{group} missing {names - have}"


def test_keys_unique():
    keys = [t.key for t in all_tools()]
    assert len(keys) == len(set(keys))
