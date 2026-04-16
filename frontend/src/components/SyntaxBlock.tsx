/**
 * SyntaxBlock — syntax-highlighted code block with truncation support.
 *
 * Replaces plain <pre> rendering in expansion previews. Uses the same
 * Prism async-light build + oneDark theme as MobileSyntaxView.
 */

import { useState, memo } from "react";
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

export const SyntaxBlock = memo(function SyntaxBlock({
  content,
  language,
  maxLength = MAX_CHARS,
  showLineNumbers = false,
  startLine = 1,
}: SyntaxBlockProps) {
  const [expanded, setExpanded] = useState(false);
  const needsTruncation = content.length > maxLength;
  const displayContent = !expanded && needsTruncation
    ? content.slice(0, maxLength) + "\n…"
    : content;

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
