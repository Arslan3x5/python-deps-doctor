"""Audit a Python project's dependency files: pins, outdated packages, Python compatibility.

Standard library plus `packaging` (already installed with pip and pytest).
"""
import re
from dataclasses import dataclass
from typing import Optional

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


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

# most serious first
SEVERITY = ["incompatible", "outdated", "unknown", "unpinned", "range", "ok"]


@dataclass
class Finding:
    dep: Dep
    status: str  # one of SEVERITY
    detail: str


def supports_python(requires_python, python_version):
    """True or False, or None when the package declares no readable Python requirement."""
    if not requires_python:
        return None
    try:
        return Version(python_version) in SpecifierSet(requires_python)
    except (InvalidSpecifier, InvalidVersion):
        return None


def _newer(latest, pinned):
    try:
        return Version(latest) > Version(pinned)
    except InvalidVersion:
        return False


def classify(dep, info, python_version):
    """Judge one dependency.

    `info` is what PyPI says: {"latest": "3.1.3", "requires_python": ">=3.9"}, where
    requires_python belongs to the pinned version. Pass None if the lookup failed.
    """
    if info is None:
        return Finding(dep, "unknown", "could not look up this package")
    if dep.pinned:
        required = info.get("requires_python")
        if supports_python(required, python_version) is False:
            return Finding(
                dep,
                "incompatible",
                f"{dep.name}=={dep.pinned} requires Python {required}, but this is Python {python_version}",
            )
        latest = info.get("latest")
        if latest and _newer(latest, dep.pinned):
            return Finding(dep, "outdated", f"{dep.pinned} -> {latest}")
        return Finding(dep, "ok", "pinned and up to date")
    if not dep.specifier:
        return Finding(dep, "unpinned", "no version rule, so installs are not reproducible")
    return Finding(dep, "range", f"version range {dep.specifier}")


def summarize(findings):
    """Count findings per status, most serious first (zero counts are left out)."""
    counts = {}
    for finding in findings:
        counts[finding.status] = counts.get(finding.status, 0) + 1
    return {status: counts[status] for status in SEVERITY if status in counts}