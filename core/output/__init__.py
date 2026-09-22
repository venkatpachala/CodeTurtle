"""core/output/__init__.py — Output adapters for ReviewFinding."""

from core.output.github_review import publish_review
from core.output.terminal import render_findings_terminal
from core.output.json_output import build_prediction_json

__all__ = ["publish_review", "render_findings_terminal", "build_prediction_json"]
