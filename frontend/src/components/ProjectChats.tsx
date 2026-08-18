import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, CheckCircle2, Link2, MessageSquare, Play, Send, Unlink } from "lucide-react";
import { toast } from "sonner";
import {
  attachChatToChain,
  createChat,
  detachChatFromChain,
  fetchChatMessages,
  fetchChats,
  fetchProjectTaskLinks,
  fetchProjects,
  launchJobFromChat,
  sendChatTurn,
} from "../api/client";
import type { Chat, ChatMessage, ProjectResponse, TaskLinkResponse } from "../api/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Spinner } from "./ui/spinner";

type SendState = "idle" | "sending" | "awaiting-assistant" | "assistant" | "error";
type ChatAction = "idle" | "launching" | "attaching" | "detaching";

export function ProjectChats() {
  const { projectId, chatId } = useParams<{ projectId?: string; chatId?: string }>();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [selected, setSelected] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [taskLinks, setTaskLinks] = useState<TaskLinkResponse[]>([]);
  const [newChatProjectId, setNewChatProjectId] = useState(projectId ?? "");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [sendState, setSendState] = useState<SendState>("idle");
  const [sendError, setSendError] = useState<string | null>(null);
  const [launchRepo, setLaunchRepo] = useState("");
  const [chainTaskLinkId, setChainTaskLinkId] = useState("");
  const [chatAction, setChatAction] = useState<ChatAction>("idle");
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => setNewChatProjectId(projectId ?? ""), [projectId]);

  const selectChat = useCallback(async (chat: Chat) => {
    setSelected(chat);
    setSendState("idle");
    setSendError(null);
    setLaunchRepo("");
    setChainTaskLinkId(chat.taskLinkId ?? "");
    setActionError(null);
    try {
      setMessages(await fetchChatMessages(chat.id));
    } catch (error) {
      setMessages([]);
      toast.error(String(error));
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    Promise.all([
      fetchChats(projectId),
      fetchProjects(),
      projectId ? fetchProjectTaskLinks(projectId) : Promise.resolve({ items: [] }),
    ])
      .then(([chatResponse, projectResponse, taskLinkResponse]) => {
        if (ignore) return;
        setChats(chatResponse.items);
        setProjects(projectResponse.items);
        setTaskLinks(taskLinkResponse.items);
        if (chatId) {
          const deepLinked = chatResponse.items.find((chat) => chat.id === chatId);
          if (deepLinked) void selectChat(deepLinked);
        }
      })
      .catch(() => { if (!ignore) toast.error("Failed to load chats"); })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [chatId, projectId, selectChat]);

  function chatUrl(chat: Chat): string {
    return chat.projectId
      ? `/projects/id/${encodeURIComponent(chat.projectId)}/chats/${encodeURIComponent(chat.id)}`
      : `/chats/${encodeURIComponent(chat.id)}`;
  }

  async function startChat() {
    if (!title.trim()) return;
    try {
      const chat = await createChat({
        title: title.trim(),
        projectId: newChatProjectId || null,
      });
      const scopedChat = newChatProjectId
        ? { ...chat, projectId: newChatProjectId }
        : chat;
      setChats((items) => [scopedChat, ...items]);
      setTitle("");
      navigate(chatUrl(scopedChat));
      await selectChat(scopedChat);
    } catch (error) {
      toast.error(String(error));
    }
  }

  async function sendMessage() {
    const content = message.trim();
    if (!selected || !content || sendState === "sending" || sendState === "awaiting-assistant") return;

    const optimisticId = `sending-${Date.now()}`;
    const optimistic: ChatMessage = {
      id: optimisticId,
      chatId: selected.id,
      role: "user",
      content,
      createdAt: new Date().toISOString(),
    };
    setMessages((items) => [...items, optimistic]);
    setSendState("sending");
    setSendError(null);
    await Promise.resolve();
    setSendState("awaiting-assistant");

    try {
      const turn = await sendChatTurn(selected.id, content);
      setMessages((items) => [
        ...items.filter((item) => item.id !== optimisticId),
        turn.userMessage,
        ...(turn.assistantMessage ? [turn.assistantMessage] : []),
      ]);
      if (turn.state === "error") {
        setSendState("error");
        setSendError(turn.error ?? "The assistant could not respond.");
        return;
      }

      setMessage("");
      setSendState("assistant");
    } catch (error) {
      setMessages((items) => items.filter((item) => item.id !== optimisticId));
      setSendState("error");
      setSendError(error instanceof Error ? error.message : String(error));
    }
  }

  function updateSelectedChat(updated: Chat) {
    setSelected(updated);
    setChats((items) => items.map((item) => item.id === updated.id ? updated : item));
    setChainTaskLinkId(updated.taskLinkId ?? "");
  }

  async function launchJob() {
    if (!selected || !launchRepo) {
      setActionError("Select a repository before launching a Job.");
      return;
    }
    setChatAction("launching");
    setActionError(null);
    try {
      const job = await launchJobFromChat(selected.id, { repo: launchRepo });
      toast.success("Job launched from Chat");
      navigate(`/jobs/${encodeURIComponent(job.id)}`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setChatAction("idle");
    }
  }

  async function attachChain() {
    if (!selected || !chainTaskLinkId) {
      setActionError("Select a Task Recipe chain to attach.");
      return;
    }
    setChatAction("attaching");
    setActionError(null);
    try {
      updateSelectedChat(await attachChatToChain(selected.id, chainTaskLinkId));
      toast.success("Chat attached to chain");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setChatAction("idle");
    }
  }

  async function detachChain() {
    if (!selected) return;
    setChatAction("detaching");
    setActionError(null);
    try {
      updateSelectedChat(await detachChatFromChain(selected.id));
      toast.success("Chat detached from chain");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    } finally {
      setChatAction("idle");
    }
  }

  if (loading) return <div className="flex justify-center py-20"><Spinner size="lg" /></div>;

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center gap-2">
        <MessageSquare size={18} />
        <h1 className="text-xl font-semibold">{projectId ? "Project Chats" : "Chats"}</h1>
      </div>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(10rem,14rem)_auto]">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="New chat title"
          onKeyDown={(event) => event.key === "Enter" && void startChat()}
        />
        <select
          value={newChatProjectId}
          onChange={(event) => setNewChatProjectId(event.target.value)}
          aria-label="Chat Project"
          className="h-9 rounded-md border border-border bg-background px-2 text-xs text-foreground"
        >
          <option value="">Unscoped</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
        </select>
        <Button onClick={() => void startChat()}>Start</Button>
      </div>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <div className="rounded-lg border border-border bg-card p-2 space-y-1">
          {chats.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No chats yet</p> : chats.map((chat) => (
            <Link
              key={chat.id}
              to={chatUrl(chat)}
              onClick={() => void selectChat(chat)}
              className={`block w-full text-left rounded-md px-3 py-2 text-sm ${selected?.id === chat.id ? "bg-accent" : "hover:bg-accent/50"}`}
            >
              <span className="block truncate">{chat.title}</span>
              <span className="text-xs text-muted-foreground">{new Date(chat.lastMessageAt).toLocaleString()}</span>
            </Link>
          ))}
        </div>
        <div className="rounded-lg border border-border bg-card p-4 min-h-40">
          {selected ? (
            <>
              <div className="flex items-baseline justify-between gap-2">
                <h2 className="font-semibold">{selected.title}</h2>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{projects.find((project) => project.id === selected.projectId)?.name ?? "Unscoped"}</span>
                  {selected.projectId && selected.taskLinkId && (
                    <Link
                      to={`/projects/id/${encodeURIComponent(selected.projectId)}/board/task/${encodeURIComponent(selected.taskLinkId)}`}
                      className="hover:text-foreground"
                    >
                      Supervising chain
                    </Link>
                  )}
                </div>
              </div>
              {selected.projectId && (
                <div className="mt-4 grid gap-3 rounded-md border border-border bg-background p-3">
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    <select
                      aria-label="Repository for launched Job"
                      value={launchRepo}
                      onChange={(event) => setLaunchRepo(event.target.value)}
                      className="h-9 rounded-md border border-border bg-background px-2 text-xs"
                    >
                      <option value="">Select repository for Job…</option>
                      {projects.find((project) => project.id === selected.projectId)?.repoPaths.map((repo) => (
                        <option key={repo} value={repo}>{repo}</option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      onClick={() => void launchJob()}
                      loading={chatAction === "launching"}
                      disabled={!launchRepo || chatAction !== "idle"}
                    >
                      <Play size={12} /> Launch Job
                    </Button>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                    <select
                      aria-label="Task Recipe chain"
                      value={chainTaskLinkId}
                      onChange={(event) => setChainTaskLinkId(event.target.value)}
                      className="h-9 rounded-md border border-border bg-background px-2 text-xs"
                    >
                      <option value="">Select Task Recipe chain…</option>
                      {taskLinks.map((link) => (
                        <option key={link.id} value={link.id}>
                          {link.storyNodeId ?? link.trackerTicketRef ?? link.id}
                        </option>
                      ))}
                    </select>
                    {selected.taskLinkId ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => void detachChain()}
                        loading={chatAction === "detaching"}
                        disabled={chatAction !== "idle"}
                      >
                        <Unlink size={12} /> Detach chain
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => void attachChain()}
                        loading={chatAction === "attaching"}
                        disabled={!chainTaskLinkId || chatAction !== "idle"}
                      >
                        <Link2 size={12} /> Attach chain
                      </Button>
                    )}
                  </div>
                  {actionError && (
                    <p role="alert" className="text-xs text-red-500">{actionError}</p>
                  )}
                </div>
              )}
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
                <Input
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Write a message…"
                  disabled={sendState === "sending" || sendState === "awaiting-assistant"}
                  onKeyDown={(event) => event.key === "Enter" && void sendMessage()}
                />
                <Button
                  size="sm"
                  onClick={() => void sendMessage()}
                  disabled={sendState === "sending" || sendState === "awaiting-assistant"}
                  aria-label="Send message"
                >
                  <Send size={14} />
                </Button>
              </div>
              <div className="mt-2 min-h-5 text-xs" aria-live="polite">
                {sendState === "sending" && <span className="text-muted-foreground">Sending…</span>}
                {sendState === "awaiting-assistant" && <span className="text-muted-foreground">Waiting for assistant…</span>}
                {sendState === "assistant" && (
                  <span className="inline-flex items-center gap-1 text-green-500"><CheckCircle2 size={12} /> Assistant replied</span>
                )}
                {sendState === "error" && (
                  <span className="inline-flex items-center gap-1 text-red-500"><AlertCircle size={12} /> {sendError}</span>
                )}
              </div>
            </>
          ) : <p className="text-sm text-muted-foreground">Select a chat to view it.</p>}
        </div>
      </div>
    </div>
  );
}
