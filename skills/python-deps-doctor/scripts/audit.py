"""Audit a Python project's dependency files: pins, outdated packages, Python compatibility.

Standard library plus `packaging` (already installed with pip and pytest).
"""
import re
from dataclasses import dataclass
from typing import Optional

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


@dataclass
class Dep:
    name: str  # canonical name, e.g. flask-sqlalchemy
    extras: tuple
    specifier: str  # e.g. ">=13.0.0" or "==3.0.3" or ""
    pinned: Optional[str]  # the exact version when the file pins one, else None
    marker: Optional[str]
    line: int


def _logical_lines(text):
    """Yield (line_number, text), joining lines that end with a backslash."""
    buffer, start = "", 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if not buffer:
            start = number
        if raw.rstrip().endswith("\\"):
            buffer += raw.rstrip()[:-1] + " "
            continue
        yield start, buffer + raw
        buffer = ""
    if buffer:
        yield start, buffer


def _strip_comment(line):
    # a '#' starts a comment only at the start or after whitespace (URLs can contain '#egg=')
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()


def _pinned_version(specifier):
    parts = list(specifier)
    if len(parts) == 1 and parts[0].operator in ("==", "===") and not parts[0].version.endswith(".*"):
        return parts[0].version
    return None


def parse_requirements(text):
    """Parse requirements.txt text. Returns (deps, skipped).

    `skipped` is a list of (line_number, line, reason) for lines that are not plain
    requirements: options, includes, editable installs, direct URLs, unparsable lines.
    """
    deps, skipped = [], []
    for number, raw in _logical_lines(text):
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith("-"):
            skipped.append((number, line, "option or include line"))
            continue
        if "://" in line or " @ " in line:
            skipped.append((number, line, "direct reference"))
            continue
        line = re.sub(r"\s--hash=\S+", "", line).strip()
        try:
            req = Requirement(line)
        except InvalidRequirement:
            skipped.append((number, line, "could not parse"))
            continue
        deps.append(
            Dep(
                name=canonicalize_name(req.name),
                extras=tuple(sorted(req.extras)),
                specifier=str(req.specifier),
                pinned=_pinned_version(req.specifier),
                marker=str(req.marker) if req.marker else None,
                line=number,
            )
        )
    return deps, skipped