"""Tests for compact tool-activity formatting helpers (pure)."""

from deerflow.tui.message_format import (
    DEFAULT_DETAIL_LIMIT,
    format_tool_detail,
    format_tool_result,
    summarize_tool_title,
    truncate,
)


def test_summarize_known_tool_titles():
    assert summarize_tool_title("read_file") == "Read"
    assert summarize_tool_title("write_file") == "Write"
    assert summarize_tool_title("bash") == "Bash"


def test_summarize_unknown_tool_falls_back_to_humanized_name():
    assert summarize_tool_title("my_custom_tool") == "My Custom Tool"


def test_format_tool_detail_extracts_salient_arg():
    assert format_tool_detail("read_file", {"path": "src/app.py"}) == "src/app.py"
    assert format_tool_detail("bash", {"command": "ls -la"}) == "ls -la"
    assert format_tool_detail("web_search", {"query": "deerflow tui"}) == "deerflow tui"


def test_format_tool_detail_unknown_args_compact_json():
    detail = format_tool_detail("mystery", {"a": 1, "b": 2})
    assert "a" in detail and "1" in detail


def test_format_tool_detail_empty_args_is_empty_string():
    assert format_tool_detail("bash", {}) == ""


def test_truncate_short_text_unchanged():
    assert truncate("hello", 80) == "hello"


def test_truncate_long_text_adds_marker():
    out = truncate("x" * 200, 50)
    assert len(out) <= 50 + 1  # marker char
    assert out.endswith("…")


def test_format_tool_result_collapses_whitespace_and_truncates():
    result = format_tool_result("line1\n\n   line2   \n", limit=80)
    assert "line1" in result and "line2" in result
    assert "\n" not in result


def test_format_tool_result_handles_non_string():
    assert format_tool_result({"ok": True}) != ""


def test_detail_subagent_prefers_description_over_prompt():
    detail = format_tool_detail("task", {"description": "Audit the dependency tree", "prompt": "Read every manifest and report archived packages"})
    assert detail == "Audit the dependency tree"


def test_detail_subagent_falls_back_to_prompt_when_description_empty():
    detail = format_tool_detail("task", {"description": "", "prompt": "Read every manifest in the repo"})
    assert detail == "Read every manifest in the repo"


def test_detail_subagent_description_is_collapsed_and_bounded():
    detail = format_tool_detail("task", {"description": "first line\n   second line " + "y" * 200})
    assert detail.startswith("first line second line")
    assert "\n" not in detail
    assert len(detail) <= DEFAULT_DETAIL_LIMIT + 1
    assert detail.endswith("…")


def test_detail_batch_task_uses_title_not_items():
    detail = format_tool_detail("batch_task", {"title": "Weekly competitor scan", "items": [{"prompt": "check A"}, {"prompt": "check B"}]})
    assert detail == "Weekly competitor scan"


def test_detail_present_files_joins_every_path():
    detail = format_tool_detail("present_files", {"filepaths": ["/mnt/outputs/report.pdf", "/mnt/outputs/chart.png"]})
    assert detail == "/mnt/outputs/report.pdf, /mnt/outputs/chart.png"


def test_detail_view_image_uses_image_path():
    assert format_tool_detail("view_image", {"image_path": "/mnt/user-data/uploads/diagram.png"}) == "/mnt/user-data/uploads/diagram.png"


def test_detail_list_value_only_joins_non_empty_strings():
    assert format_tool_detail("present_files", {"filepaths": [123, 456]}) == '{"filepaths":[123,456]}'
    assert format_tool_detail("present_files", {"filepaths": []}) == '{"filepaths":[]}'
    assert format_tool_detail("present_files", {"filepaths": ["", "   "]}) == '{"filepaths":["","   "]}'


def test_detail_unknown_tool_still_falls_back_to_json():
    detail = format_tool_detail("mystery", {"image_path": "/tmp/x.png"})
    assert detail == '{"image_path":"/tmp/x.png"}'
