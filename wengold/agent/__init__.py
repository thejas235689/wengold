"""An agent layer over the validity kernel: six stages, plus three agent patterns."""
from .adaptation import Bandit
from .loop import Agent, AgentRun, SimulatedRunner
from .orchestra import Executor, Handoff, Orchestra, Planner, Review, Reviewer
from .perception import Context, perceive
from .planning import STRATEGIES, best_first, cheapest, greedy, plan
from .react import ReActRun, Step, react
from .reasoning import Thought, Trace, explain, explain_all
from .search import beam, best_of_k, sample_orders, scaling_curve, score_order, single

__all__ = ["Agent", "AgentRun", "SimulatedRunner", "Bandit", "Context", "perceive",
           "plan", "STRATEGIES", "cheapest", "greedy", "best_first",
           "explain", "explain_all", "Thought", "Trace",
           # ReAct
           "react", "ReActRun", "Step",
           # test-time scaling
           "single", "best_of_k", "beam", "score_order", "sample_orders",
           "scaling_curve",
           # multi-agent
           "Orchestra", "Planner", "Executor", "Reviewer", "Review", "Handoff"]
