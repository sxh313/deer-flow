"""Regression anchor: the custom-skill rollback route must keep its filesystem IO off the loop.

``rollback_custom_skill`` offloads storage construction, existence probes, the
``custom/.history/<name>.jsonl`` read, the frontmatter validation's temporary
directory, and the post-scan read of the file it is about to replace, each
through ``asyncio.to_thread`` — the same rule ``get_custom_skill_history``
applies. History entries contain the full previous and new skill content, so
reading and parsing them on the Gateway loop stalls other requests, and the
accepted rollback path additionally answers with ``_read_custom_skill_response``,
which walks every installed skill.

The first two branches return before the awaited security scan, so they need no
scanner stub: the 404 branch covers construction plus the existence probes, and
the out-of-range branch covers the full history-file read and parse. The third
drives an accepted rollback with a stubbed model scan.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException, Request

from app.gateway.routers.skills import SkillRollbackRequest, rollback_custom_skill
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.runtime.user_context import get_effective_user_id

pytestmark = pytest.mark.asyncio

_SKILL_NAME = "loop-rollback-skill"
_SKILL_MD = f"---\nname: {_SKILL_NAME}\ndescription: Anchor fixture skill.\n---\n\n# {_SKILL_NAME}\n"


def _custom_dir() -> Path:
    return get_paths().user_custom_skills_dir(get_effective_user_id())


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr("deerflow.config.paths._paths", None)


def _admin_request() -> Request:
    # AuthMiddleware normally supplies this state; keep the real admin check.
    user = SimpleNamespace(id=UUID("11111111-2222-3333-4444-555555555555"), system_role="admin")
    return Request({"type": "http", "headers": [], "state": {"user": user}})


def _install_skill() -> None:
    skill_dir = _custom_dir() / _SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(_SKILL_MD, encoding="utf-8")


def _write_history(records: list[dict]) -> None:
    history_dir = _custom_dir() / ".history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{_SKILL_NAME}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


async def test_rollback_missing_skill_does_not_block_event_loop() -> None:
    """The 404 branch must not resolve paths or probe the filesystem from the loop."""
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=0), _admin_request(), config)

    assert excinfo.value.status_code == 404


async def test_rollback_history_read_does_not_block_event_loop() -> None:
    """The out-of-range branch reads and parses the whole history file first."""
    await asyncio.to_thread(_install_skill)
    await asyncio.to_thread(_write_history, [{"action": "edit", "ts": 1, "prev_content": _SKILL_MD, "new_content": _SKILL_MD}])
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    with pytest.raises(HTTPException) as excinfo:
        await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=99), _admin_request(), config)

    assert excinfo.value.status_code == 400
    assert "history_index is out of range" in str(excinfo.value.detail)


async def test_rollback_current_content_read_after_the_scan_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The accepted rollback reads the file it is about to replace, and that read is blocking IO too."""
    await asyncio.to_thread(_install_skill)
    await asyncio.to_thread(_write_history, [{"action": "edit", "ts": 1, "prev_content": _SKILL_MD, "new_content": _SKILL_MD}])
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})

    async def _allow(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(decision="allow", reason="clean")

    monkeypatch.setattr("app.gateway.routers.skills.scan_skill_content", _allow)

    await rollback_custom_skill(_SKILL_NAME, SkillRollbackRequest(history_index=0), _admin_request(), config)
