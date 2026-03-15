import { useRef, useEffect, useState, useCallback } from "react";
import { Send, Bot, User } from "lucide-react";
import { toast } from "sonner";
import { useTowerStore, selectJobTranscript } from "../store";
import { sendOperatorMessage } from "../api/client";
import { MicButton } from "./VoiceButton";
import { Input } from "./ui/input";
import { Button } from "./ui/button";

export function TranscriptPanel({ jobId, interactive }: { jobId: string; interactive?: boolean }) {
  const entries = useTowerStore(selectJobTranscript(jobId));
  const viewportRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [msg, setMsg] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (stickRef.current && viewportRef.current) {
      viewportRef.current.scrollTo({ top: viewportRef.current.scrollHeight });
    }
  }, [entries.length]);

  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  const handleSend = useCallback(async () => {
    if (!msg.trim()) return;
    setSending(true);
    try {
      await sendOperatorMessage(jobId, msg.trim());
      setMsg("");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSending(false);
    }
  }, [jobId, msg]);

  return (
    <div className="flex flex-col h-full overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
        <span className="text-sm font-semibold text-muted-foreground">Transcript</span>
        <span className="text-xs text-muted-foreground">{entries.length} messages</span>
      </div>

      <div
        ref={viewportRef}
        className="flex-1 min-h-0 overflow-y-auto"
        onScroll={handleScroll}
      >
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">No messages yet</p>
        ) : (
          <div className="p-3 space-y-2">
            {entries.map((e, i) => {
              const isAgent = e.role === "agent";
              return (
                <div key={i} className={`flex gap-2 ${isAgent ? "" : "flex-row-reverse"}`}>
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-1 ${
                    isAgent ? "bg-blue-900/50" : "bg-green-900/50"
                  }`}>
                    {isAgent ? <Bot size={14} /> : <User size={14} />}
                  </div>
                  <div className={`max-w-[90%] sm:max-w-[80%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                    isAgent ? "bg-muted rounded-tl-sm" : "bg-blue-900/30 rounded-tr-sm"
                  }`}>
                    <div className="whitespace-pre-wrap">{e.content}</div>
                    <span className="text-xs text-muted-foreground mt-1 block">
                      {new Date(e.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {interactive && (
        <div className="p-2 border-t border-border shrink-0">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Input
                placeholder="Send instruction to agent…"
                value={msg}
                onChange={(e) => setMsg(e.currentTarget.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                disabled={sending}
                className="pr-8"
              />
              <div className="absolute right-2 top-1/2 -translate-y-1/2">
                <MicButton onTranscript={(t) => setMsg((prev) => (prev ? prev + " " : "") + t)} />
              </div>
            </div>
            <Button
              size="icon"
              onClick={handleSend}
              disabled={sending || !msg.trim()}
              loading={sending}
            >
              <Send size={16} />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
