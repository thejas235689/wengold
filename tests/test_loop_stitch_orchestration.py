from wengold.verification.orchestration import (
    AgentReport, AgentStatus, AgentTask, LoopPolicy, LoopStitchCoordinator,
    RunStatus, Stitcher,
)


class FakeAgent:
    def __init__(self, agent_id, fn, depends_on=()):
        self.task = AgentTask(agent_id, tuple(depends_on))
        self.fn = fn
        self.calls = 0

    def execute(self, context):
        self.calls += 1
        return self.fn(context, self.calls)


def test_loop_retries_retryable_failure_then_passes():
    agent = FakeAgent("sim", lambda _ctx, call: AgentReport(
        "sim", AgentStatus.FAIL if call == 1 else AgentStatus.PASS,
        outputs={"sim_ok": True} if call > 1 else {},
        retryable=call == 1,
    ))
    result = LoopStitchCoordinator().run(
        [agent], policy=LoopPolicy(max_iterations=3), required_outputs=("sim_ok",)
    )
    assert result.status is RunStatus.PASS
    assert result.iterations == 2


def test_retry_limit_never_turns_failure_into_pass():
    agent = FakeAgent("formal", lambda _ctx, _call: AgentReport(
        "formal", AgentStatus.FAIL, retryable=True
    ))
    result = LoopStitchCoordinator().run([agent], policy=LoopPolicy(max_iterations=2))
    assert result.status is RunStatus.INCOMPLETE
    assert result.iterations == 2


def test_stitch_reports_conflicts_without_silent_precedence():
    reports = [
        AgentReport("lint", AgentStatus.PASS, {"top": "core_a"}),
        AgentReport("elab", AgentStatus.PASS, {"top": "core_b"}),
    ]
    result = Stitcher().stitch(reports, required_keys=("top",))
    assert not result.consistent
    assert "top" in result.conflicts


def test_stitch_explicit_resolution_is_auditable():
    reports = [
        AgentReport("lint", AgentStatus.PASS, {"top": "core_a"}),
        AgentReport("elab", AgentStatus.PASS, {"top": "core_b"}),
    ]
    result = Stitcher().stitch(reports, resolutions={"top": "elab"})
    assert result.consistent
    assert result.outputs["top"] == "core_b"


def test_dependency_order_and_context_stitching():
    child = FakeAgent("sim", lambda ctx, _call: AgentReport(
        "sim", AgentStatus.PASS, {"sim_seen": ctx["rtl_digest"]}
    ), depends_on=("frontend",))
    frontend = FakeAgent("frontend", lambda _ctx, _call: AgentReport(
        "frontend", AgentStatus.PASS, {"rtl_digest": "sha256:abc"}
    ))
    result = LoopStitchCoordinator().run([child, frontend], required_outputs=("sim_seen",))
    assert result.status is RunStatus.PASS
    assert child.calls == 1
    assert result.stitch.outputs["sim_seen"] == "sha256:abc"


def test_failed_dependency_blocks_downstream_agent():
    frontend = FakeAgent("frontend", lambda _ctx, _call: AgentReport(
        "frontend", AgentStatus.FAIL, retryable=False
    ))
    sim = FakeAgent("sim", lambda _ctx, _call: AgentReport("sim", AgentStatus.PASS),
                    depends_on=("frontend",))
    result = LoopStitchCoordinator().run([frontend, sim])
    assert result.status is RunStatus.FAIL
    assert sim.calls == 0
    assert result.reports[1].status is AgentStatus.BLOCKED


def test_agent_dependency_cycle_is_rejected():
    a = FakeAgent("a", lambda _ctx, _call: AgentReport("a", AgentStatus.PASS), ("b",))
    b = FakeAgent("b", lambda _ctx, _call: AgentReport("b", AgentStatus.PASS), ("a",))
    try:
        LoopStitchCoordinator().run([a, b])
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("expected cycle rejection")


def test_failed_agent_outputs_are_not_stitched():
    report = AgentReport("bad", AgentStatus.FAIL, {"fake_pass": True})
    result = Stitcher().stitch([report], required_keys=("fake_pass",))
    assert "fake_pass" not in result.outputs
    assert result.missing_required == ("fake_pass",)



def test_agent_exception_is_recorded_as_error_not_pass():
    def explode(_context, _call):
        raise RuntimeError("adapter crashed")

    agent = FakeAgent("sim", explode)
    result = LoopStitchCoordinator().run([agent])
    assert result.status is RunStatus.BLOCKED
    assert result.reports[0].status is AgentStatus.ERROR
    assert "adapter crashed" in result.reports[0].findings[0]


def test_empty_agent_set_is_rejected():
    try:
        LoopStitchCoordinator().run([])
    except ValueError as exc:
        assert "at least one" in str(exc)
    else:
        raise AssertionError("expected empty agent set rejection")


def test_ledger_records_iterations_and_final_result(tmp_path):
    from wengold.ledger.store import Ledger

    ledger = Ledger(tmp_path / "loop-stitch.jsonl")
    agent = FakeAgent("lint", lambda _ctx, _call: AgentReport(
        "lint", AgentStatus.PASS, {"lint_clean": True}
    ))
    result = LoopStitchCoordinator().run(
        [agent], required_outputs=("lint_clean",), ledger=ledger
    )
    assert result.status is RunStatus.PASS
    kinds = [record["kind"] for record in ledger]
    assert kinds == ["loop_stitch_iteration", "loop_stitch_result"]
    assert ledger.audit().ok
