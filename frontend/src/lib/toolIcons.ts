/**
 * Tool name → codicon glyph resolution.
 *
 * Maps tool names into 6 categories so the step list shows meaningful
 * but not overwhelming iconography. Unknown / MCP tools fall through
 * to the generic dot.
 */

import type { CodiconName } from "../components/ui/codicon";

type ToolCategory = "terminal" | "file-read" | "file-write" | "search" | "agent" | "other";

const CATEGORY_MAP: Record<string, ToolCategory> = {
  bash: "terminal",
  run_in_terminal: "terminal",
  get_terminal_output: "terminal",
  read_file: "file-read",
  list_dir: "file-read",
  create_file: "file-write",
  replace_string_in_file: "file-write",
  multi_replace_string_in_file: "file-write",
  grep_search: "search",
  semantic_search: "search",
  file_search: "search",
  runSubagent: "agent",
  search_subagent: "agent",
};

const CATEGORY_ICON: Record<ToolCategory, CodiconName> = {
  terminal: "terminal",
  "file-read": "file-code",
  "file-write": "edit",
  search: "search",
  agent: "robot",
  other: "circle-small-filled",
};

export function resolveToolIcon(toolName?: string): CodiconName {
  if (!toolName) return "circle-small-filled";
  // Strip MCP server prefix (e.g. "github/search_code" → "search_code")
  const name = toolName.includes("/") ? toolName.split("/").pop()! : toolName;
  return CATEGORY_ICON[CATEGORY_MAP[name] ?? "other"];
}
