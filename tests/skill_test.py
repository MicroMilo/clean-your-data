#!/usr/bin/env python3
"""Static contract checks for the distributable Agent Skills."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def frontmatter(text: str) -> str:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    return match.group(1)


def main() -> int:
    primary_dir = ROOT / "skills" / "clean-your-data"
    primary = (primary_dir / "SKILL.md").read_text(encoding="utf-8")
    primary_yaml = (primary_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
    primary_frontmatter = frontmatter(primary)
    assert "name: clean-your-data" in primary_frontmatter
    assert len(primary.splitlines()) < 100
    assert 'cyd why "PATH" --format json' in primary
    assert "action_gate" in primary
    assert "never authorizes or moves anything" in primary
    assert "Do not use `sudo`" in primary
    assert "allow_implicit_invocation: false" in primary_yaml
    assert "$clean-your-data" in primary_yaml
    assert "cyd why --help" in primary
    assert "wait for approval" in primary
    assert "@v0.5.0" in primary
    assert "/main/skills/clean-your-data" not in primary

    legacy_dir = ROOT / "audit-local-files"
    legacy = (legacy_dir / "SKILL.md").read_text(encoding="utf-8")
    legacy_yaml = (legacy_dir / "agents" / "openai.yaml").read_text(encoding="utf-8")
    legacy_frontmatter = frontmatter(legacy)
    assert "name: audit-local-files" in legacy_frontmatter
    assert len(legacy.splitlines()) < 80
    assert "compatibility" in legacy.lower()
    assert "allow_implicit_invocation: false" in legacy_yaml

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    skill_url = "https://github.com/MicroMilo/clean-your-data/tree/v0.5.0/skills/clean-your-data"
    assert skill_url in readme
    assert skill_url in readme_zh
    assert "uv tool install --force" in readme
    assert "uv tool install --force" in readme_zh

    print("skill test ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
