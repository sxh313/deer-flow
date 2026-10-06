"""Regression tests for skill-review Markdown report rendering.

The report body is what a human or CI reads out of ``review_skill_package``
(``artifact.markdown.en/zh``), so a page that claims "no issues" while listing
required actions is a user-visible defect even though the JSON report is valid.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from deerflow.skills.review.analyzer import analyze_skill_package
from deerflow.skills.review.models import PackageLimits
from deerflow.skills.review.readers import LocalDirectoryReader
from deerflow.skills.review.renderer import build_static_report, render_report_markdown

NO_ISSUE_LINE = "- No deterministic or semantic issues were reported."
CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "skill_review" / "review_report.v1.schema.json"

# Loopback HTTP reference keeps the deterministic scanner at "info" severity, which the
# report schema cannot carry as an issue (enum is blocker/major/minor).
LOOPBACK_SKILL_MD = """---
name: local-http-probe
description: Probe package that references a loopback HTTP endpoint.
---

# Local HTTP probe

Fetch the status page from http://127.0.0.1:8080/status before running the check.
"""


def _findings_section(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    start = lines.index("## Findings") + 1
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip():
            out.append(line)
    return out


def _facts(*findings: dict[str, Any], truncated: bool = False) -> dict[str, Any]:
    severities = {finding["severity"] for finding in findings}
    return {
        "schema_version": "review_facts.v1",
        "subject": {"display_ref": "inline://SKILL.md", "package_digest": "0" * 64},
        "profile": "deerflow",
        "completeness": {
            "package_enumerated": True,
            "text_content_complete": not truncated,
            "truncated": truncated,
            "not_assessed": ["full_package"] if truncated else [],
        },
        "summary": {
            "blockers": sum(1 for f in findings if f["severity"] == "blocker"),
            "errors": sum(1 for f in findings if f["severity"] == "error"),
            "warnings": sum(1 for f in findings if f["severity"] == "warning"),
            "infos": sum(1 for f in findings if f["severity"] == "info"),
        },
        "findings": list(findings),
        "reader_errors": [],
        "analyzer_errors": [],
        "evals": {"case_count": 0},
        "scanners_used": ["skillscan"] if severities else [],
    }


def _finding(severity: str, rule_id: str, path: str, line: int) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "path": path,
        "line": line,
        "message": f"{rule_id} message for {path}:{line}",
        "remediation": f"Confirm {rule_id} is expected for this skill.",
    }


def _truncated_loopback_facts() -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a real package through the production reader with ``--max-files 2``."""
    with tempfile.TemporaryDirectory(prefix="skill-review-render-") as tmp:
        root = Path(tmp)
        (root / "SKILL.md").write_text(LOOPBACK_SKILL_MD, encoding="utf-8", newline="\n")
        (root / "notes-a.md").write_text("alpha\n", encoding="utf-8", newline="\n")
        (root / "notes-b.md").write_text("beta\n", encoding="utf-8", newline="\n")
        snapshot = LocalDirectoryReader(root, limits=PackageLimits(max_files=2)).read()
    facts = analyze_skill_package(snapshot, profile="deerflow")
    assert snapshot["truncated"] is True
    assert facts["completeness"]["truncated"] is True, facts["completeness"]
    return facts, build_static_report(facts)


def test_report_without_findings_still_claims_no_issues() -> None:
    facts = _facts()
    report = build_static_report(facts)
    markdown = render_report_markdown(report, facts, locale="en")
    assert _findings_section(markdown) == [NO_ISSUE_LINE]


def test_finding_free_report_renders_without_facts_argument() -> None:
    report = build_static_report(_facts())
    markdown = render_report_markdown(report, locale="en")
    assert _findings_section(markdown) == [NO_ISSUE_LINE]
    assert report["recommended_actions"] == []


def test_advisory_finding_is_rendered_with_location_next_to_its_action() -> None:
    facts, report = _truncated_loopback_facts()
    advisories = [f for f in facts["findings"] if f["severity"] not in {"blocker", "error", "warning"}]
    assert [(f["rule_id"], f["path"], f["line"]) for f in advisories] == [("network-local-http", "SKILL.md", 8)], facts["findings"]
    assert report["recommended_actions"], report
    assert report["issues"] == []

    section = _findings_section(render_report_markdown(report, facts, locale="en"))
    assert NO_ISSUE_LINE not in section, section
    assert any(line.startswith("- info network-local-http at SKILL.md:8: ") for line in section), section


def test_issue_and_advisory_findings_each_render_once() -> None:
    warning = _finding("warning", "structure-missing-evals", "SKILL.md", 3)
    info = _finding("info", "network-local-http", "SKILL.md", 8)
    facts = _facts(warning, info, truncated=True)
    report = build_static_report(facts)
    markdown = render_report_markdown(report, facts, locale="en")
    section = _findings_section(markdown)

    assert [line for line in section if "structure-missing-evals" in line] == ["- minor deterministic.1.structure-missing-evals at SKILL.md:3: structure-missing-evals message for SKILL.md:3"], section
    assert [line for line in section if "network-local-http" in line] == ["- info network-local-http at SKILL.md:8: network-local-http message for SKILL.md:8"], section
    assert NO_ISSUE_LINE not in section, section


def test_advisory_findings_never_enter_the_report_issue_list() -> None:
    facts = _facts(_finding("error", "package-executable-binary", "bin/tool", 1), _finding("info", "network-local-http", "SKILL.md", 8), truncated=True)
    report = build_static_report(facts)
    enum = set(json.loads(CONTRACT.read_text(encoding="utf-8"))["properties"]["issues"]["items"]["properties"]["severity"]["enum"])

    assert [issue["rule_id"] if "rule_id" in issue else issue["id"] for issue in report["issues"]] == ["deterministic.1.package-executable-binary"]
    assert {issue["severity"] for issue in report["issues"]} <= enum
    assert "info" not in {issue["severity"] for issue in report["issues"]}
    assert any(line.startswith("- info network-local-http at SKILL.md:8: ") for line in _findings_section(render_report_markdown(report, facts, locale="en")))


def test_advisory_rendering_stays_bounded_like_the_actions_it_pairs_with() -> None:
    findings = [_finding("info", f"network-probe-{i}", "SKILL.md", i + 1) for i in range(7)]
    facts = _facts(*findings, truncated=True)
    report = build_static_report(facts)
    section = _findings_section(render_report_markdown(report, facts, locale="en"))

    assert len(report["recommended_actions"]) == 5, report["recommended_actions"]
    assert len(section) == 5, section
    assert [line.split(" ")[2] for line in section] == [f"network-probe-{i}" for i in range(5)], section
