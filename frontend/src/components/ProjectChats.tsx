import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { MessageSquare, Send } from "lucide-react";
import { toast } from "sonner";
import { addChatMessage, createChat, fetchChatMessages, fetchChats } from "../api/client";
import type { Chat, ChatMessage } from "../api/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Spinner } from "./ui/spinner";

export function ProjectChats() {
  const { projectId } = useParams<{ projectId: string }>();
  const [chats, setChats] = useState<Chat[]>([]);
  const [selected, setSelected] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!projectId) return;
    let ignore = false;
    setLoading(true);
    fetchChats()
      .then((res) => {
        if (ignore) return;
        setChats(res.items.filter((chat) => chat.projectId === projectId));
      })
      .catch(() => { if (!ignore) toast.error("Failed to load chats"); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [projectId]);

  async function selectChat(chat: Chat) {
    setSelected(chat);
    try {
      setMessages(await fetchChatMessages(chat.id));
    } catch (error) {
      setMessages([]);
      toast.error(String(error));
    }
  }

  async function startChat() {
    if (!title.trim()) return;
    if (!projectId) {
      toast.error("No Project selected. Chats must belong to a Project.");
      return;
    }
    try {
      const chat = await createChat({ title: title.trim(), projectId });
      setChats((items) => [chat, ...items]);
      await selectChat(chat);
      setTitle("");
    } catch (error) {
      toast.error(String(error));
    }
  }

  async function sendMessage() {
    if (!selected || !message.trim()) return;
    try {
      const added = await addChatMessage(selected.id, message.trim());
      setMessages((items) => [...items, added]);
      setMessage("");
      toast.success("Message added");
    } catch (error) {
      toast.error(String(error));
    }
  }

  if (loading) return <div className="flex justify-center py-20"><Spinner size="lg" /></div>;

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center gap-2">
        <MessageSquare size={18} />
        <h1 className="text-xl font-semibold">Chats</h1>
      </div>
      <div className="flex gap-2">
        <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="New chat title" onKeyDown={(event) => event.key === "Enter" && startChat()} />
        <Button onClick={startChat}>Start</Button>
      </div>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <div className="rounded-lg border border-border bg-card p-2 space-y-1">
          {chats.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No chats yet</p> : chats.map((chat) => (
            <button key={chat.id} type="button" onClick={() => selectChat(chat)} className={`w-full text-left rounded-md px-3 py-2 text-sm ${selected?.id === chat.id ? "bg-accent" : "hover:bg-accent/50"}`}>
              <span className="block truncate">{chat.title}</span>
              <span className="text-xs text-muted-foreground">{new Date(chat.lastMessageAt).toLocaleString()}</span>
            </button>
          ))}
        </div>
        <div className="rounded-lg border border-border bg-card p-4 min-h-40">
          {selected ? (
            <>
              <h2 className="font-semibold">{selected.title}</h2>
              <div className="mt-4 space-y-2 max-h-80 overflow-y-auto" aria-live="polite">
                {messages.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No messages yet.</p>
                ) : messages.map((item) => (
                  <div key={item.id} className={`rounded-md px-3 py-2 text-sm ${item.role === "user" ? "bg-primary/10 ml-6" : "bg-muted mr-6"}`}>
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{item.role}</p>
                    <p className="whitespace-pre-wrap">{item.content}</p>
                  </div>
                ))}
              </div>
              <div className="flex gap-2 mt-6">
                <Input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Write a message…" onKeyDown={(event) => event.key === "Enter" && sendMessage()} />
                <Button size="sm" onClick={sendMessage} aria-label="Send message"><Send size={14} /></Button>
              </div>
            </>
          ) : <p className="text-sm text-muted-foreground">Select a chat to view it.</p>}
        </div>
      </div>
    </div>
  );
}
