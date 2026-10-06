"""Regression: `secret-cloud-token` must see the separators modern keys use.

OpenAI spells the vendor as a leading `-`-separated segment (`sk-proj-`,
`sk-svcacct-`, `sk-admin-`) and Anthropic uses `sk-ant-api03-`, so the body of a
real `sk-` key contains `-`/`_`. The canonical API-key detector in
`pii_redaction_middleware._API_KEY_PATTERN` already spells the family
`sk-[A-Za-z0-9_-]{20,}`; SkillScan's `_SECRET_TOKEN_PATTERNS` must agree, or a
bare embedded key (with no `KEY=`/`KEY:` assignment to lean on) is missed
entirely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.agents.middlewares.pii_redaction_middleware import _API_KEY_PATTERN
from deerflow.skills.skillscan.orchestrator import _scan_text_file, scan_skill_dir

_LEGACY = "sk-" + "A" * 48
_PROJECT = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6" * 2
_SERVICE_ACCOUNT = "sk-svcacct-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6" * 2
_ANTHROPIC = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6" * 2

_SK_TOKENS = (_LEGACY, _PROJECT, _SERVICE_ACCOUNT, _ANTHROPIC)


def _cloud_token_severities(text: str, rel_path: str = "scripts/run.sh") -> list[str]:
    return [finding["severity"] for finding in _scan_text_file(rel_path, text) if finding["rule_id"] == "secret-cloud-token"]


@pytest.mark.parametrize("token", _SK_TOKENS)
def test_bare_sk_token_is_flagged_critical(token: str) -> None:
    # No `token=`/`token:` assignment is present, so only the token patterns can catch it.
    text = f'curl -H "Authorization: Bearer {token}" https://api.example.com/v1/models\n'
    assert _cloud_token_severities(text) == ["CRITICAL"]


@pytest.mark.parametrize("token", _SK_TOKENS)
def test_skillscan_and_pii_redactor_agree_on_sk_keys(token: str) -> None:
    assert _API_KEY_PATTERN.search(token) is not None
    assert _cloud_token_severities(f"value = {token!r}\n") == ["CRITICAL"]


def test_sk_prefix_word_that_is_not_a_key_stays_quiet() -> None:
    # Too few characters after the prefix to be a key.
    assert _cloud_token_severities("run sk-learn-and-pandas first\n") == []
    # No word boundary before `sk`, so the prefix is not a token start.
    assert _cloud_token_severities("a risk-free-very-long-string-here\n") == []


def test_scan_skill_dir_blocks_a_skill_carrying_a_modern_key(tmp_path: Path) -> None:
    root = tmp_path / "demo-skill"
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n\nBody.\n", encoding="utf-8")
    (root / "scripts" / "run.sh").write_text(
        f'curl -H "Authorization: Bearer {_ANTHROPIC}" https://api.anthropic.com/v1/messages\n',
        encoding="utf-8",
    )

    result = scan_skill_dir(root)

    assert "secret-cloud-token" in [finding["rule_id"] for finding in result["findings"]]
    assert result["blocked"] is True
