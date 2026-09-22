"""Versioned external CLI argument contracts used by static review analysis.

Each entry represents a stable public dependency contract, with a source URL so
the rule can be audited and updated independently from the review model.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CliArgumentContract:
    executable: str
    option: str
    accepted: re.Pattern[str]
    description: str
    source_url: str


GIFSICLE_RESIZE_FIT = CliArgumentContract(
    executable="gifsicle",
    option="--resize-fit",
    accepted=re.compile(r"^\d+(?:x(?:\d+|_))$|^_(?:x\d+)$"),
    description="expects a widthxheight geometry, with either dimension optionally '_'; percentage syntax is not accepted by this option",
    source_url="https://github.com/kohler/gifsicle/blob/master/gifsicle.1",
)


def violates_gifsicle_resize_fit(value: str) -> bool:
    """True only for a non-empty argument outside the documented geometry grammar."""
    text = str(value or "").strip()
    return bool(text) and not bool(GIFSICLE_RESIZE_FIT.accepted.fullmatch(text))
