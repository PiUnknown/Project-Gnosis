# ============================================================
# PATCH YOUR EXISTING: src/orchestrator.py
#
# Add ONE optional parameter and ONE line per agent.
# Your agent functions themselves do not change at all.
# ============================================================
#
# BEFORE (your current code, roughly):
#
#   def run_pipeline(state: ArchaeonState):
#       ingestion_agent(state)
#       ast_parser_agent(state)
#       dependency_graph_agent(state)
#       complexity_scorer_agent(state)
#       code_rag_agent(state)
#       explainability_agent(state)
#       doc_generator_agent(state)
#
# ── AFTER (add the highlighted lines) ────────────────────────────────────────
#
# The only change: accept an optional `on_agent_complete` callback,
# and call it with the agent index (0-6) after each agent finishes.

from typing import Callable, Optional

# Import your agents — adjust to match your actual import paths
from src.agents.ingestion import run as ingestion_agent
from src.agents.ast_parser import run as ast_parser_agent
from src.agents.dependency_graph import run as dependency_graph_agent
from src.agents.complexity_scorer import run as complexity_scorer_agent
from src.agents.code_rag import run as code_rag_agent
from src.agents.explainability import run as explainability_agent
from src.agents.doc_generator import run as doc_generator_agent
from src.state import ArchaeonState


def run_pipeline(
    state: ArchaeonState,
    on_agent_complete: Optional[Callable[[int], None]] = None,  # ← ADD THIS
) -> ArchaeonState:
    """
    Sequential 7-agent pipeline.
    on_agent_complete(i) is called after agent i finishes.
    When called from the API, this updates the job store so the
    frontend sees real-time progress. When called from the CLI
    or tests, omit the callback — behaviour is identical to before.
    """
    agents = [
        ingestion_agent,
        ast_parser_agent,
        dependency_graph_agent,
        complexity_scorer_agent,
        code_rag_agent,
        explainability_agent,
        doc_generator_agent,
    ]

    for i, agent_fn in enumerate(agents):
        agent_fn(state)                                    # ← unchanged
        if on_agent_complete:                              # ← ADD THIS
            on_agent_complete(i)                           # ← ADD THIS

    return state


# ── CLI entry point (unchanged) ───────────────────────────────────────────────
# Your existing CLI / run.py continues to work exactly as before
# because on_agent_complete defaults to None.
#
# Example:
#   python run.py --url https://github.com/tiangolo/fastapi
#
# This calls run_pipeline(state) with no callback — no behaviour change.
