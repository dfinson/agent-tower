import { useState, useCallback, type ReactNode, type FormEvent } from "react";
import { sendOperatorMessage } from "../api/client";

export function OperatorMessageInput({ jobId }: { jobId: string }): ReactNode {
  const [content, setContent] = useState("");
  const [sending, setSending] = useState(false);

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const trimmed = content.trim();
      if (!trimmed) return;
      setSending(true);
      try {
        await sendOperatorMessage(jobId, trimmed);
        setContent("");
      } catch {
        // ApiError already thrown
      } finally {
        setSending(false);
      }
    },
    [jobId, content],
  );

  return (
    <form className="operator-message" onSubmit={handleSubmit}>
      <input
        className="operator-message__input"
        type="text"
        placeholder="Send a message to the agent…"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        disabled={sending}
      />
      <button
        className="btn btn--sm operator-message__send"
        type="submit"
        disabled={sending || !content.trim()}
      >
        Send
      </button>
    </form>
  );
}
