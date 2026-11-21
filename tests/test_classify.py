import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "python-deps-doctor" / "scripts"))

import audit  # noqa: E402


def dep(line):
    return audit.parse_requirements(line)[0][0]


def test_supports_python():
    assert audit.supports_python(">=3.8,<3.13", "3.12.10") is True
    assert audit.supports_python(">=3.8,<3.13", "3.14.3") is False


def test_supports_python_when_unknown():
    assert audit.supports_python(None, "3.12.0") is None
    assert audit.supports_python("", "3.12.0") is None
    assert audit.supports_python("not a specifier", "3.12.0") is None


def test_incompatible_with_this_python():
    # the real problem: rembg 2.0.59 does not install on Python 3.14
    info = {"latest": "2.0.87", "requires_python": ">=3.8,<3.13"}
    finding = audit.classify(dep("rembg==2.0.59"), info, "3.14.3")
    assert finding.status == "incompatible"
    assert "3.14.3" in finding.detail


def test_incompatible_beats_outdated():
    info = {"latest": "9.0", "requires_python": "<3.0"}
    assert audit.classify(dep("old==1.0"), info, "3.12.0").status == "incompatible"


def test_outdated():
    info = {"latest": "3.1.3", "requires_python": ">=3.8"}
    finding = audit.classify(dep("Flask==3.0.3"), info, "3.12.0")
    assert finding.status == "outdated"
    assert finding.detail == "3.0.3 -> 3.1.3"


def test_up_to_date_and_ahead_of_latest_are_ok():
    info = {"latest": "3.1.3", "requires_python": ">=3.8"}
    assert audit.classify(dep("Flask==3.1.3"), info, "3.12.0").status == "ok"
    assert audit.classify(dep("Flask==3.2.0rc1"), info, "3.12.0").status == "ok"


def test_unpinned_range_and_unknown():
    info = {"latest": "13.0.0", "requires_python": ">=3.10"}
    assert audit.classify(dep("Pillow"), info, "3.12.0").status == "unpinned"
    assert audit.classify(dep("Pillow>=13.0.0"), info, "3.12.0").status == "range"
    assert audit.classify(dep("Pillow==13.0.0"), None, "3.12.0").status == "unknown"


def test_summarize_orders_by_severity_and_skips_zero():
    info = {"latest": "3.1.3", "requires_python": ">=3.8"}
    findings = [
        audit.classify(dep("Flask==3.1.3"), info, "3.12.0"),
        audit.classify(dep("Werkzeug==3.0.4"), {"latest": "3.1.0", "requires_python": ">=3.8"}, "3.12.0"),
        audit.classify(dep("requests"), info, "3.12.0"),
    ]
    summary = audit.summarize(findings)
    assert list(summary) == ["outdated", "unpinned", "ok"]
    assert summary == {"outdated": 1, "unpinned": 1, "ok": 1}