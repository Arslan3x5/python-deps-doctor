import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "python-deps-doctor" / "scripts"))

import audit  # noqa: E402


def parse_one(line):
    deps, skipped = audit.parse_requirements(line)
    assert len(deps) == 1 and not skipped
    return deps[0]


def test_exact_pin():
    dep = parse_one("Flask==3.0.3")
    assert dep.name == "flask"
    assert dep.pinned == "3.0.3"
    assert dep.specifier == "==3.0.3"


def test_range_is_not_a_pin():
    dep = parse_one("Pillow>=13.0.0")
    assert dep.pinned is None
    assert dep.specifier == ">=13.0.0"


def test_unpinned_package():
    dep = parse_one("requests")
    assert dep.pinned is None
    assert dep.specifier == ""


def test_wildcard_is_not_a_pin():
    assert parse_one("numpy==2.*").pinned is None


def test_extras_and_marker():
    dep = parse_one('rembg[cpu]==2.0.82 ; python_version >= "3.10"')
    assert dep.extras == ("cpu",)
    assert dep.pinned == "2.0.82"
    assert dep.marker == 'python_version >= "3.10"'


def test_name_is_canonicalized():
    assert parse_one("Flask_SQLAlchemy==3.1.1").name == "flask-sqlalchemy"


def test_comments_and_blank_lines_are_ignored():
    text = "# web\n\nFlask==3.0.3  # keep in sync\n"
    deps, skipped = audit.parse_requirements(text)
    assert [d.name for d in deps] == ["flask"]
    assert deps[0].line == 3
    assert skipped == []


def test_hashes_do_not_break_parsing():
    text = "requests==2.31.0 \\\n    --hash=sha256:abc \\\n    --hash=sha256:def\n"
    deps, skipped = audit.parse_requirements(text)
    assert deps[0].pinned == "2.31.0"
    assert skipped == []


def test_unusual_lines_are_reported_as_skipped():
    text = "\n".join([
        "-r base.txt",
        "-e .",
        "--index-url https://example.com/simple",
        "git+https://github.com/x/y.git",
        "pkg @ https://example.com/pkg.zip",
        "this is not a requirement!!",
        "Flask==3.0.3",
    ])
    deps, skipped = audit.parse_requirements(text)
    assert [d.name for d in deps] == ["flask"]
    assert [reason for _, _, reason in skipped] == [
        "option or include line",
        "option or include line",
        "option or include line",
        "direct reference",
        "direct reference",
        "could not parse",
    ]