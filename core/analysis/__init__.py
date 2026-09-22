"""Deterministic, bounded program-analysis signals for PR review."""

from core.analysis.risk_signals import RiskSignal, analyze_risk_signals, attach_signals_to_bundles

__all__ = ["RiskSignal", "analyze_risk_signals", "attach_signals_to_bundles"]
