---
name: python-deps-doctor
description: Audit and safely repair a Python project's dependencies. Use whenever the user mentions requirements.txt, pip install failures, "no matching distribution found", "requires a different Python version", Dependabot or security alerts on Python packages, outdated or pinned packages, upgrading Python, Pillow, numpy, Flask or similar libraries, or asks whether their dependencies still work on a newer Python, even if they never say "audit". Runs a bundled script that checks every package in requirements files against PyPI and a target Python version, then guides upgrades that are tested before anything is committed.
compatibility: Needs Python 3.8 or newer, the packaging library (installed with pip), and internet access to pypi.org for the lookup.
---

# Python Dependency Doctor

Dependencies rot quietly. A pin that worked last year can stop installing on a newer Python, or collect security alerts. This skill finds those problems with a script, then walks through fixing them in a way that cannot break the user's working setup.

## Step 1: Find the dependency files

Look in the project folder for `requirements*.txt`, `pyproject.toml` and `setup.cfg`. The bundled script reads `requirements*.txt` only. If the project uses `pyproject.toml` or `setup.cfg`, read the dependency list from there yourself and apply the same reasoning by hand. Tell the user which files you could and could not check.

## Step 2: Run the audit script

```
python scripts/audit.py <project-folder>
python scripts/audit.py <project-folder> --python 3.14.3
```

The path to `scripts/audit.py` is relative to this skill's folder. Use `--python` when the user plans to move to a different Python version, because that is how you find packages that will break before they do. Without it, the script checks against the Python that runs it.

The script prints a Markdown report, worst problems first. Its exit code is 0 when nothing needs action, 1 when something is incompatible or outdated, and 2 when no requirements file was found.

## Step 3: Read the report

| Status | Meaning | What to do |
| --- | --- | --- |
| incompatible | The pinned version does not support the target Python | Fix first: it will not install. Look for a newer release that supports the Python version, or tell the user to use an older Python. |
| outdated | A newer release exists | Upgrade in a batch, after the incompatible ones. Read the changelog before major version jumps. |
| unknown | PyPI could not be reached or does not know the package | Check the name and the network. Do not guess a status. |
| unpinned | No version rule at all | Suggest a pin or a lower bound so installs are reproducible. |
| range | A version range such as `>=13.0.0` | Usually fine. Mention it only if it hides a risk. |
| ok | Pinned and up to date | Leave alone. |

Lines the script skipped (`-r` includes, `-e` editable installs, direct URLs) are listed at the bottom of the report. It does not analyse them, so say so.

## Step 4: Check security separately

The script does not look for vulnerabilities. Never tell the user their dependencies are secure based on this report alone. For security, do one of these:

- Run `pip-audit -r requirements.txt` if pip-audit is installed, or offer to install it with `pip install pip-audit`.
- Read the Dependabot or security alerts the user pastes in, and match each alert to its package and fixed version.

Treat packages with open alerts as the highest priority, even if the script calls them ok or only slightly outdated.

## Step 5: Plan the upgrades

Work in this order, and explain the order to the user:

1. Incompatible packages, because nothing else can be tested until they install.
2. Packages with security alerts.
3. Everything else that is outdated.

Keep `[extras]` (for example `rembg[cpu]`) and environment markers (the part after `;`) exactly as they are when you change a version. Ask whether the user prefers exact pins (`==`) or lower bounds (`>=`) and follow their style.

## Step 6: Test in a fresh environment

Never upgrade inside the user's global Python. Create a new virtual environment, install the planned versions there, and check:

```
python -m venv .venv-audit
.venv-audit/bin/python -m pip install -r requirements.txt     # Windows: .venv-audit\Scripts\python.exe
.venv-audit/bin/python -m pip check
```

Then run the project's tests, or start the app and try its main feature. Call the virtual environment's Python directly instead of activating it: on Windows, PowerShell often blocks the activation script. If anything fails, put the old `requirements.txt` back (`git checkout requirements.txt`) and report what broke instead of pushing on.

## Step 7: Report

Run the script again on the final file and show before and after. Use this format:

```
Dependency audit: <project>
Checked against Python <version>

Before: 1 incompatible, 4 outdated
After:  5 ok

Changes
- rembg 2.0.59 -> 2.0.87 (was incompatible with Python 3.14)
- pillow 11.0.0 -> 13.0.0 (security alert closed)

Tested: pip check passed; app started and processed a sample image
Not checked: vulnerabilities beyond the alerts you gave me; lines the script skipped
```

Only list a test as passed if you ran it.

## Things that go wrong

- **Pinned packages that cap the Python version.** A message like "requires Python <3.13" is a real limit. Fix it by upgrading the package or using an older Python. Do not edit the package's metadata.
- **Windows `pip freeze > requirements.txt`.** PowerShell 5 writes UTF-16. The script reads it, but other tools may not. Suggest re-saving the file as UTF-8.
- **Major upgrades.** After a major version change of an imaging, data or web library, run the code that uses it before trusting the result.
- **Offline or blocked PyPI.** Every package shows as unknown. Report that plainly and stop.

## Example

Input: `requirements.txt` with `Flask==3.0.3`, `rembg==2.0.59`, `Pillow==11.0.0`, `numpy==2.0.2`, `Werkzeug==3.0.4`, checked with `--python 3.14.3`.

Output:

```
Summary: 1 incompatible, 4 outdated

| Package | Rule | Status | Detail |
| --- | --- | --- | --- |
| rembg | ==2.0.59 | incompatible | rembg==2.0.59 requires Python <3.13,>=3.8, but this is Python 3.14.3 |
| flask | ==3.0.3 | outdated | 3.0.3 -> 3.1.3 |
| numpy | ==2.0.2 | outdated | 2.0.2 -> 2.5.5 |
| pillow | ==11.0.0 | outdated | 11.0.0 -> 13.0.0 |
| werkzeug | ==3.0.4 | outdated | 3.0.4 -> 3.1.9 |
```

Versions in the table come from the date the script ran and will differ over time.
