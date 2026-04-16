/**
 * SyntaxBlock — syntax-highlighted code block with truncation support.
 *
 * Replaces plain <pre> rendering in expansion previews. Uses the same
 * Prism async-light build + oneDark theme as MobileSyntaxView.
 *
 * Detects and strips line-number prefixes (e.g. "1. ", "12: ", "  3 | ")
 * from tool output, then renders a proper gutter instead.
 */

import { useState, useMemo, memo } from "react";
import SyntaxHighlighter from "react-syntax-highlighter/dist/esm/prism-async-light";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

interface SyntaxBlockProps {
  content: string;
  language?: string;
  maxLength?: number;
  showLineNumbers?: boolean;
  startLine?: number;
}

const MAX_CHARS = 800;

/**
 * Detect whether content lines have a leading line-number prefix.
 * Returns the stripped content + detected start line, or null if no prefix found.
 *
 * Supported formats:
 *   "1. code"        (dot)
 *   "1: code"        (colon)
 *   "  1 | code"     (pipe)
 *   "  1\tcode"      (tab after number)
 */
const LINE_NUM_RE = /^(\s*)(\d+)([.:]\s|\s*\|\s?|\t)/;

function stripLineNumbers(text: string): { stripped: string; startLine: number } | null {
  const lines = text.split("\n");
  // Need at least 3 non-empty lines to confidently detect a pattern
  const nonEmpty = lines.filter((l) => l.trim().length > 0);
  if (nonEmpty.length < 3) return null;

  // Check that most non-empty lines match the pattern and numbers are sequential
  let prevNum = -1;
  let firstNum = -1;
  let matchCount = 0;
  for (const line of nonEmpty) {
    const m = LINE_NUM_RE.exec(line);
    if (!m) continue;
    const num = parseInt(m[2]!, 10);
    if (firstNum === -1) firstNum = num;
    if (prevNum !== -1 && num !== prevNum + 1) return null; // non-sequential → not line numbers
    prevNum = num;
    matchCount++;
  }

  // Require >80% of non-empty lines to match
  if (matchCount / nonEmpty.length < 0.8) return null;
  if (firstNum === -1) return null;

  // Strip the prefix from every line
  const stripped = lines
    .map((line) => {
      if (line.trim().length === 0) return "";
      const m = LINE_NUM_RE.exec(line);
      return m ? line.slice(m[0].length) : line;
    })
    .join("\n");

  return { stripped, startLine: firstNum };
}

export const SyntaxBlock = memo(function SyntaxBlock({
  content,
  language,
  maxLength = MAX_CHARS,
  showLineNumbers: showLineNumbersProp = false,
  startLine: startLineProp = 1,
}: SyntaxBlockProps) {
  const [expanded, setExpanded] = useState(false);

  // Detect and strip embedded line-number prefixes
  const parsed = useMemo(() => stripLineNumbers(content), [content]);
  const cleanContent = parsed ? parsed.stripped : content;
  const showLineNumbers = parsed ? true : showLineNumbersProp;
  const startLine = parsed ? parsed.startLine : startLineProp;

  const needsTruncation = cleanContent.length > maxLength;
  const displayContent = !expanded && needsTruncation
    ? cleanContent.slice(0, maxLength) + "\n…"
    : cleanContent;

  return (
    <div className="overflow-hidden">
      <div className="overflow-x-auto">
        <SyntaxHighlighter
          language={language ?? "text"}
          style={oneDark}
          customStyle={{
            margin: 0,
            padding: showLineNumbers ? 0 : "0.375rem 0.75rem",
            background: "transparent",
            fontSize: "12px",
            lineHeight: "1.55",
          }}
          codeTagProps={{
            style: { background: "transparent" },
          }}
          showLineNumbers={showLineNumbers}
          startingLineNumber={startLine}
          lineNumberContainerStyle={{
            float: "left",
            paddingRight: 0,
            paddingTop: "0.375rem",
            paddingBottom: "0.375rem",
            marginRight: 0,
            borderRight: "1px solid rgba(255,255,255,0.06)",
            textAlign: "right",
            userSelect: "none" as const,
            background: "transparent",
          }}
          lineNumberStyle={{
            minWidth: "2.5em",
            paddingRight: "0.75em",
            paddingLeft: "0.75em",
            color: "rgba(255,255,255,0.2)",
          }}
          wrapLongLines={false}
        >
          {displayContent}
        </SyntaxHighlighter>
      </div>
      {needsTruncation && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-primary hover:underline px-3 pb-1.5"
        >
          {expanded ? "Show less" : `Show all (${content.length.toLocaleString()} chars)`}
        </button>
      )}
    </div>
  );
});
