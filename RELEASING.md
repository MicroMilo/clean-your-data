# Releasing Clean Your Data

Releases are tag-driven. Do not create a tag until every step below passes from a clean checkout.

## Preflight

1. Confirm `pyproject.toml`, `src/clean_your_data/__init__.py`, and `CHANGELOG.md` use the same version.
2. Review `README.md`, `PRIVACY.md`, and `SECURITY.md` whenever data flow or cleanup behavior changes.
3. Check tracked files for personal absolute paths, credentials, local reports, databases, and cleanup history.
4. Run every test on Python 3.9 and 3.12 through GitHub Actions.

## Local Build

```bash
python3 -m venv /tmp/cyd-release-venv
/tmp/cyd-release-venv/bin/python -m pip install --upgrade pip build twine
/tmp/cyd-release-venv/bin/python -m compileall -q src audit-local-files/scripts tests
for test in tests/*_test.py; do /tmp/cyd-release-venv/bin/python "$test"; done
/tmp/cyd-release-venv/bin/python -m build
/tmp/cyd-release-venv/bin/python -m twine check dist/*
```

Install the wheel into a second empty environment and verify `cyd --version`, `cyd gui --help`, `cyd config ai --show`, and a bounded scan. Confirm the wheel contains `clean_your_data/web/index.html`.

## Tag

After reviewing the exact commit:

```bash
git tag -a v0.4.0 -m "Clean Your Data v0.4.0"
git push origin main
git push origin v0.4.0
```

The release workflow reruns compilation and tests, builds the wheel and source archive, validates both distributions, checks the packaged GUI asset, and attaches the artifacts to the GitHub release.
