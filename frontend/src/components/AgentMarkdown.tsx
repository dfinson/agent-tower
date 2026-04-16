import { memo, Component, Children, isValidElement, cloneElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import SyntaxHighlighter from "react-syntax-highlighter/dist/esm/prism-async-light";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

/** Error boundary for markdown rendering — shows raw text on crash. */
class MarkdownErrorBoundary extends Component<{ fallback: string; children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  render() {
    if (this.state.hasError) return <pre className="text-xs whitespace-pre-wrap">{this.props.fallback}</pre>;
    return this.props.children;
  }
}

/** Highlight substring matches inside a text string. */
function highlightText(text: string, query: string): ReactNode {
  if (!query) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(${escaped})`, "gi");
  const parts = text.split(re);
  if (parts.length === 1) return text;
  return parts.map((part, i) =>
    re.test(part)
      ? <mark key={i} className="bg-yellow-400/50 text-foreground rounded-sm px-0.5 ring-1 ring-yellow-400/40">{part}</mark>
      : <span key={i}>{part}</span>,
  );
}

/** Recursively walk React children, applying highlighter to string nodes. */
function mapChildren(children: ReactNode, mapper: (text: string) => ReactNode): ReactNode {
  return Children.map(children, (child) => {
    if (typeof child === "string") return mapper(child);
    if (isValidElement(child) && child.props.children) {
      return cloneElement(child, {}, mapChildren(child.props.children, mapper));
    }
    return child;
  });
}

/** Shared markdown renderer for agent messages — used by CuratedFeed. */
export const AgentMarkdown = memo(function AgentMarkdown({ content, highlight }: { content: string; highlight?: string }) {
  const hl = highlight ? (children: ReactNode) => mapChildren(children, (t) => highlightText(t, highlight)) : (children: ReactNode) => children;
  return (
    <MarkdownErrorBoundary fallback={content}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0">{hl(children)}</p>,
        ul: ({ children }) => <ul className="mb-2 pl-4 list-disc space-y-0.5">{children}</ul>,
        ol: ({ children }) => <ol className="mb-2 pl-4 list-decimal space-y-0.5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed">{hl(children)}</li>,
        h1: ({ children }) => <h1 className="text-[17px] sm:text-base font-semibold mb-1 mt-2 first:mt-0">{hl(children)}</h1>,
        h2: ({ children }) => <h2 className="text-[15px] sm:text-sm font-semibold mb-1 mt-2 first:mt-0">{hl(children)}</h2>,
        h3: ({ children }) => <h3 className="text-[15px] sm:text-sm font-medium mb-1 mt-1 first:mt-0">{hl(children)}</h3>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-muted-foreground/40 pl-3 text-muted-foreground italic my-2">
            {children}
          </blockquote>
        ),
        code: ({ className, children }) => {
          const match = /language-(\w+)/.exec(className ?? "");
          const lang = match ? match[1] : undefined;
          const code = String(children).replace(/\n$/, "");
          return lang ? (
            <div className="my-2 rounded-md border border-border overflow-hidden">
              <SyntaxHighlighter
                language={lang}
                style={oneDark}
                customStyle={{
                  margin: 0,
                  padding: "0.5rem 0.75rem",
                  background: "var(--background)",
                  fontSize: "12px",
                  lineHeight: "1.55",
                }}
                wrapLongLines={false}
              >
                {code}
              </SyntaxHighlighter>
            </div>
          ) : className?.startsWith("language-") ? (
            <pre className="bg-background border border-border rounded-md p-2 sm:p-3 my-2 overflow-x-auto max-w-full text-[13px] sm:text-xs font-mono">
              <code>{children}</code>
            </pre>
          ) : (
            <code className="bg-background border border-border rounded px-1 py-0.5 text-[13px] sm:text-xs font-mono">
              {children}
            </code>
          );
        },
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2 hover:opacity-80">
            {children}
          </a>
        ),
        hr: () => <hr className="border-border my-2" />,
        table: ({ children }) => (
          <div className="overflow-x-auto my-2">
            <table className="text-xs border-collapse w-full">{children}</table>
          </div>
        ),
        th: ({ children }) => (
          <th className="border border-border px-2 py-1 bg-muted font-semibold text-left">{children}</th>
        ),
        td: ({ children }) => (
          <td className="border border-border px-2 py-1">{children}</td>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
    </MarkdownErrorBoundary>
  );
});
