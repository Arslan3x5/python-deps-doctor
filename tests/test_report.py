import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "python-deps-doctor" / "scripts"))

import audit  # noqa: E402


def fake_pypi(data):
    def get_json(url):
        if url not in data:
            raise OSError("404")
        return data[url]

    return get_json


PYPI_DATA = {
    "https://pypi.org/pypi/flask/json": {"info": {"version": "3.1.3", "requires_python": ">=3.9"}},
    "https://pypi.org/pypi/flask/3.0.3/json": {"info": {"version": "3.0.3", "requires_python": ">=3.8"}},
}


def test_fetch_info_pinned_uses_the_pinned_versions_python_requirement():
    info = audit.fetch_info("flask", "3.0.3", get_json=fake_pypi(PYPI_DATA))
    assert info == {"latest": "3.1.3", "requires_python": ">=3.8"}


def test_fetch_info_unpinned_uses_latest():
    info = audit.fetch_info("flask", None, get_json=fake_pypi(PYPI_DATA))
    assert info == {"latest": "3.1.3", "requires_python": ">=3.9"}


def test_fetch_info_returns_none_on_failure():
    assert audit.fetch_info("missing", "1.0", get_json=fake_pypi(PYPI_DATA)) is None
    assert audit.fetch_info("flask", "9.9.9", get_json=fake_pypi(PYPI_DATA)) is None
    assert audit.fetch_info("flask", None, get_json=fake_pypi({"https://pypi.org/pypi/flask/json": {}})) is None


def test_find_requirements(tmp_path):
    for name in ("requirements.txt", "requirements-dev.txt", "notes.txt"):
        (tmp_path / name).write_text("flask\n")
    assert [p.name for p in audit.find_requirements(tmp_path)] == ["requirements-dev.txt", "requirements.txt"]


def test_reads_utf16_files_made_by_powershell(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_bytes("Flask==3.0.3\r\n".encode("utf-16"))
    assert "Flask==3.0.3" in audit.read_requirements_text(path)


def test_render_report_puts_worst_first_and_lists_skipped():
    deps, skipped = audit.parse_requirements("Flask==3.1.3\nrembg==2.0.59\n-r base.txt\n")
    infos = {
        "flask": {"latest": "3.1.3", "requires_python": ">=3.9"},
        "rembg": {"latest": "2.0.87", "requires_python": ">=3.8,<3.13"},
    }
    findings = [audit.classify(d, infos[d.name], "3.14.3") for d in deps]
    text = audit.render_report("requirements.txt", findings, skipped, "3.14.3")
    assert "Summary: 1 incompatible, 1 ok" in text
    assert text.index("| rembg |") < text.index("| flask |")
    assert "line 3: `-r base.txt`" in text


def test_main_exit_code_and_output(tmp_path, monkeypatch, capsys):
    (tmp_path / "requirements.txt").write_text("Flask==3.0.3\nrembg==2.0.59\n")
    infos = {
        "flask": {"latest": "3.1.3", "requires_python": ">=3.8"},
        "rembg": {"latest": "2.0.87", "requires_python": ">=3.8,<3.13"},
    }
    monkeypatch.setattr(audit, "fetch_info", lambda name, pinned=None: infos[name])
    code = audit.main([str(tmp_path), "--python", "3.14.3"])
    output = capsys.readouterr().out
    assert code == 1
    assert "incompatible" in output and "outdated" in output


def test_main_without_requirements_files(tmp_path, capsys):
    assert audit.main([str(tmp_path)]) == 2
    assert "No requirements" in capsys.readouterr().out