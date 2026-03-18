from backend.services.tool_formatters import extract_tool_issue


class TestExtractToolIssue:
    def test_prefers_json_error_fields(self) -> None:
        result = '{"error": "oldString not found in file", "details": "replace failed"}'
        assert extract_tool_issue(result) == "oldString not found in file"

    def test_falls_back_to_first_meaningful_line(self) -> None:
        result = "warning: no matches found\nsearched 0 files"
        assert extract_tool_issue(result) == "warning: no matches found"

    def test_returns_none_for_empty_result(self) -> None:
        assert extract_tool_issue("   ") is None