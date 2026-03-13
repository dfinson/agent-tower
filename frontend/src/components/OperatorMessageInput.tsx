import { useState, useCallback } from "react";
import { sendOperatorMessage } from "../api/client";
import { Button } from "../ui/Button";
import { Input } from "../ui/Form";
import { toast } from "sonner";

export function OperatorMessageInput({ jobId }: { jobId: string }) {
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);

  const handleSend = useCallback(async () => {
    if (!message.trim()) return;
    setSending(true);
    try {
      await sendOperatorMessage(jobId, message.trim());
      setMessage("");
      toast.success("Message sent");
    } catch (e) {
      toast.error(`Failed to send: ${e}`);
    } finally {
      setSending(false);
    }
  }, [jobId, message]);

  return (
    <div className="flex gap-2 mt-3">
      <Input
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="Send message to agent…"
        onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
        disabled={sending}
      />
      <Button size="sm" disabled={sending || !message.trim()} onClick={handleSend}>
        {sending ? "Sending…" : "Send"}
      </Button>
    </div>
  );
}
