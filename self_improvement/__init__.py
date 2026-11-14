"""Controlled self-improvement primitives for Personal AI Brain.

All APIs are inert by default. Diagnostics are read-only; proposal and
solution-store mutations require explicit caller invocation.
"""
from .core import collect_diagnostics, analyze_quality_events, build_improvement_proposal
from .store import ImprovementEventStore, SolutionLibrary

__all__ = [
    "collect_diagnostics",
    "analyze_quality_events",
    "build_improvement_proposal",
    "ImprovementEventStore",
    "SolutionLibrary",
]
