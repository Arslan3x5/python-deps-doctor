"""Audit a Python project's dependency files: pins, outdated packages, Python compatibility.

Standard library plus `packaging` (already installed with pip and pytest).
"""
import argparse
import json
import platform
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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

PYPI = "https://pypi.org/pypi"


def _get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def fetch_info(name, pinned=None, get_json=_get_json):
    """Ask PyPI for the latest version and the pinned version's Requires-Python.

    Returns None when PyPI cannot be reached or does not know the package or version.
    `get_json` is passed in so tests can use a fake and need no network.
    """
    try:
        latest = get_json(f"{PYPI}/{name}/json")["info"]
        info = {"latest": latest["version"], "requires_python": latest.get("requires_python")}
        if pinned:
            info["requires_python"] = get_json(f"{PYPI}/{name}/{pinned}/json")["info"].get("requires_python")
        return info
    except (OSError, ValueError, KeyError):  # network errors, bad JSON, missing fields
        return None


def find_requirements(project_dir):
    """The requirements*.txt files in the project folder, sorted by name."""
    return sorted(Path(project_dir).glob("requirements*.txt"))


def read_requirements_text(path):
    """Read a requirements file, including the UTF-16 files PowerShell's `pip freeze >` creates."""
    raw = Path(path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def analyze(path, python_version, fetch=fetch_info):
    """Parse one requirements file and judge every dependency. Returns (findings, skipped)."""
    deps, skipped = parse_requirements(read_requirements_text(path))
    findings = [classify(dep, fetch(dep.name, dep.pinned), python_version) for dep in deps]
    return findings, skipped


def render_report(filename, findings, skipped, python_version):
    """A Markdown report: summary, one table row per dependency (worst first), skipped lines."""
    lines = [f"## {filename} (checked against Python {python_version})", ""]
    summary = summarize(findings)
    lines.append("Summary: " + (", ".join(f"{count} {status}" for status, count in summary.items()) or "no dependencies found"))
    lines.append("")
    if findings:
        lines += ["| Package | Rule | Status | Detail |", "| --- | --- | --- | --- |"]
        for f in sorted(findings, key=lambda f: (SEVERITY.index(f.status), f.dep.name)):
            lines.append(f"| {f.dep.name} | {f.dep.specifier or '(none)'} | {f.status} | {f.detail} |")
        lines.append("")
    if skipped:
        lines.append("Skipped lines:")
        lines += [f"- line {number}: `{text}` ({reason})" for number, text, reason in skipped]
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="audit.py", description="Audit requirements*.txt files.")
    parser.add_argument("project", nargs="?", default=".", help="project folder (default: current folder)")
    parser.add_argument("--python", default=platform.python_version(), help="Python version to check against (default: the running one)")
    args = parser.parse_args(argv)

    files = find_requirements(args.project)
    if not files:
        print(f"No requirements*.txt found in {args.project}")
        return 2

    cache = {}

    def fetch(name, pinned):
        if (name, pinned) not in cache:
            cache[(name, pinned)] = fetch_info(name, pinned)
        return cache[(name, pinned)]

    problems = 0
    for path in files:
        findings, skipped = analyze(path, args.python, fetch)
        print(render_report(path.name, findings, skipped, args.python))
        problems += sum(1 for f in findings if f.status in ("incompatible", "outdated"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())