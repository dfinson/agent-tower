/**
 * Chat panel for the metrics composer.
 *
 * Users type natural language questions, the system generates SQL queries,
 * executes them, and renders results with a visualization template.
 * Users can pin results as permanent dashboard tiles.
 */

import { useState, useRef, useEffect } from "react";
import {
  MessageSquare, Send, Pin, Loader2, ChevronDown, ChevronUp,
  AlertCircle, Sparkles,
} from "lucide-react";
import {
  sendMetricsChatMessage,
  pinMetric,
  clearMetricsChatConversation,
  type MetricsChatMessage,
} from "../../api/client-metrics";
import { MetricViz } from "./VizTemplates";
import { MicButton } from "../VoiceButton";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: MetricsChatMessage;
  timestamp: Date;
}

interface MetricsChatPanelProps {
  period?: number;
  onMetricPinned?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MetricsChatPanel({ period, onMetricPinned }: MetricsChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const waveformRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = chatContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const handleSend = async () => {
    const question = input.trim();
    if (!question || loading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: question,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const resp = await sendMetricsChatMessage(
        question,
        conversationId ?? undefined,
        period,
      );
      setConversationId(resp.conversationId);

      const assistantMsg: ChatMessage = {
        id: resp.message.messageId,
        role: "assistant",
        content: resp.message.narrative,
        response: resp.message,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const errorMsg: ChatMessage = {
        id: `error-${Date.now()}`,
        role: "assistant",
        content: err instanceof Error ? err.message : "Something went wrong",
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handlePin = async (msg: MetricsChatMessage, question: string) => {
    const firstSql = msg.sqlQueries?.[0];
    if (!msg.vizData || !firstSql) return;
    const vizType = msg.viz ?? "table";
    try {
      await pinMetric({
        name: msg.title ?? "Custom Metric",
        sql: firstSql,
        viz: vizType,
        vizConfig: msg.vizConfig,
        originalQuestion: question,
        explanation: msg.narrative,
      });
      onMetricPinned?.();
    } catch {
      // Swallow — pin failure is non-critical
    }
  };

  const handleNewConversation = () => {
    if (conversationId) {
      clearMetricsChatConversation(conversationId).catch(() => {});
    }
    setMessages([]);
    setConversationId(null);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-accent/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-indigo-400" />
          <span className="text-sm font-medium text-foreground">Metrics Composer</span>
          {messages.length > 0 && (
            <span className="text-xs text-muted-foreground">
              ({messages.filter((m) => m.role === "user").length} questions)
            </span>
          )}
        </div>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {expanded && (
        <div className="border-t border-border">
          {/* Messages */}
          <div ref={chatContainerRef} className="max-h-[500px] overflow-y-auto px-4 py-3 space-y-4">
            {messages.length === 0 && (
              <div className="text-center py-8">
                <MessageSquare size={24} className="mx-auto text-muted-foreground/50 mb-2" />
                <p className="text-sm text-muted-foreground">
                  Ask a question about your telemetry data
                </p>
                <div className="mt-3 flex flex-wrap gap-2 justify-center">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => setInput(s)}
                      className="text-xs px-2.5 py-1 rounded-full border border-border text-muted-foreground hover:text-foreground hover:border-indigo-500/50 transition-colors"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, idx) => (
              <ChatBubble
                key={msg.id}
                message={msg}
                onPin={msg.response && !msg.response.error ? () => {
                  const q = messages.slice(0, idx).reverse().find(m => m.role === "user")?.content ?? "";
                  return handlePin(msg.response!, q);
                } : undefined}
              />
            ))}

            {loading && (
              <div className="flex items-center gap-2 text-muted-foreground py-2">
                <Loader2 size={14} className="animate-spin" />
                <span className="text-sm">Analyzing your data...</span>
              </div>
            )}
          </div>

          {/* Input */}
          <div className="border-t border-border px-4 py-3">
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about your telemetry data..."
                  rows={1}
                  className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-indigo-500/50"
                />
                <div ref={waveformRef} />
              </div>
              <MicButton
                onTranscript={(text) => setInput((prev) => prev ? prev + " " + text : text)}
                onStateChange={() => {}}
                waveformContainerRef={waveformRef}
              />
              <button
                onClick={handleSend}
                disabled={!input.trim() || loading}
                className="rounded-md bg-indigo-600 px-3 py-2 text-white hover:bg-indigo-500 disabled:opacity-40 transition-colors"
              >
                <Send size={14} />
              </button>
            </div>
            {messages.length > 0 && (
              <button
                onClick={handleNewConversation}
                className="mt-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                New conversation
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat bubble
// ---------------------------------------------------------------------------

function ChatBubble({
  message,
  onPin,
}: {
  message: ChatMessage;
  onPin?: () => void;
}) {
  const [sqlExpanded, setSqlExpanded] = useState(false);
  const [pinning, setPinning] = useState(false);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-indigo-600/20 border border-indigo-500/30 px-3 py-2">
          <p className="text-sm text-foreground">{message.content}</p>
        </div>
      </div>
    );
  }

  const resp = message.response;

  return (
    <div className="space-y-2">
      {/* Narrative */}
      <div className="max-w-[90%]">
        {resp?.error ? (
          <div className="flex items-start gap-2 rounded-lg bg-red-500/10 border border-red-500/30 px-3 py-2">
            <AlertCircle size={14} className="text-red-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm text-red-300">{message.content}</p>
              {resp.suggestion && (
                <p className="text-xs text-muted-foreground mt-1">
                  Suggestion: {resp.suggestion}
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="rounded-lg bg-accent/30 border border-border px-3 py-2">
            <p className="text-sm text-foreground">{message.content}</p>
          </div>
        )}
      </div>

      {/* Visualization */}
      {resp && !resp.error && resp.vizData && resp.vizData.length > 0 && (
        <div className="rounded-lg border border-border bg-card/50 p-3">
          {resp.title && (
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-medium text-foreground">{resp.title}</h4>
              {onPin && (
                <button
                  onClick={async () => {
                    setPinning(true);
                    await onPin();
                    setPinning(false);
                  }}
                  disabled={pinning}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-indigo-400 transition-colors"
                  title="Pin to dashboard"
                >
                  {pinning ? <Loader2 size={12} className="animate-spin" /> : <Pin size={12} />}
                  Pin
                </button>
              )}
            </div>
          )}
          <MetricViz
            viz={resp.viz ?? "table"}
            data={resp.vizData}
            config={(resp.vizConfig ?? {}) as Record<string, unknown>}
          />
        </div>
      )}

      {/* SQL queries (collapsible) */}
      {resp?.sqlQueries && resp.sqlQueries.length > 0 && (
        <div>
          <button
            onClick={() => setSqlExpanded(!sqlExpanded)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {sqlExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            {resp.sqlQueries.length} {resp.sqlQueries.length === 1 ? "query" : "queries"} executed
          </button>
          {sqlExpanded && (
            <div className="mt-1 space-y-1">
              {resp.sqlQueries.map((sql, i) => (
                <pre
                  key={i}
                  className="text-xs bg-background/50 rounded px-2 py-1.5 overflow-x-auto text-muted-foreground font-mono"
                >
                  {sql}
                </pre>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suggestion prompts
// ---------------------------------------------------------------------------

const SUGGESTIONS = [
  "What's my total spend this week?",
  "Which model is most cost-effective?",
  "Show tool failure rate by category",
  "Average job duration trend over last 30 days",
  "Cost breakdown by activity type",
];
