/* eslint-disable @typescript-eslint/no-explicit-any */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("../../api/client", () => ({
  createChat: vi.fn(),
  fetchChatMessages: vi.fn(),
  fetchChats: vi.fn(),
  fetchProjects: vi.fn(),
  sendChatTurn: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import {
  fetchChatMessages,
  fetchChats,
  fetchProjects,
  sendChatTurn,
} from "../../api/client";
import { ProjectChats } from "../ProjectChats";

const chat = {
  id: "chat-1",
  projectId: "project-1",
  title: "Architecture",
  createdAt: "2026-08-17T10:00:00Z",
  lastMessageAt: "2026-08-17T10:00:00Z",
  status: "open",
  taskLinkId: null,
};

function renderChats() {
  return render(
    <MemoryRouter initialEntries={["/projects/id/project-1/chats/chat-1"]}>
      <Routes>
        <Route path="/projects/id/:projectId/chats/:chatId" element={<ProjectChats />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchChats).mockResolvedValue({ items: [chat] } as any);
  vi.mocked(fetchProjects).mockResolvedValue({
    items: [{ id: "project-1", name: "Payments", repoPaths: ["/repo/payments"] }],
  } as any);
  vi.mocked(fetchChatMessages).mockResolvedValue([]);
});

describe("ProjectChats", () => {
  it("loads a deep-linked Chat within its owning Project", async () => {
    renderChats();

    expect(await screen.findAllByText("Architecture")).toHaveLength(2);
    expect(fetchChats).toHaveBeenCalledWith("project-1");
    expect(fetchChatMessages).toHaveBeenCalledWith("chat-1");
    expect(screen.getAllByText("Payments")).toHaveLength(2);
  });

  it("renders the persisted assistant response after sending", async () => {
    vi.mocked(sendChatTurn).mockResolvedValue({
      userMessage: {
        id: "message-1",
        chatId: "chat-1",
        role: "user",
        content: "What should we do?",
        createdAt: "2026-08-17T10:01:00Z",
      },
      assistantMessage: {
        id: "message-2",
        chatId: "chat-1",
        role: "assistant",
        content: "Compare the tradeoffs first.",
        createdAt: "2026-08-17T10:01:01Z",
      },
      state: "assistant",
      error: null,
    });
    renderChats();

    const input = await screen.findByPlaceholderText("Write a message…");
    fireEvent.change(input, { target: { value: "What should we do?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Compare the tradeoffs first.")).toBeInTheDocument();
    expect(screen.getByText("Assistant replied")).toBeInTheDocument();
  });

  it("shows an explicit assistant failure and keeps the draft for retry", async () => {
    vi.mocked(sendChatTurn).mockResolvedValue({
      userMessage: {
        id: "message-1",
        chatId: "chat-1",
        role: "user",
        content: "Try this",
        createdAt: "2026-08-17T10:01:00Z",
      },
      assistantMessage: null,
      state: "error",
      error: "Assistant unavailable",
    });
    renderChats();

    const input = await screen.findByPlaceholderText("Write a message…");
    fireEvent.change(input, { target: { value: "Try this" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Assistant unavailable")).toBeInTheDocument();
    await waitFor(() => expect(input).toHaveValue("Try this"));
  });
});
