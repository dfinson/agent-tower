import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within, fireEvent } from "@testing-library/react";

vi.mock("../../api/client", () => ({
  fetchCredentials: vi.fn(),
  fetchCredentialGuidance: vi.fn(),
  createCredential: vi.fn(),
  deleteCredential: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { fetchCredentials, fetchCredentialGuidance, createCredential, deleteCredential } from "../../api/client";
import { IntegrationsSettings } from "../IntegrationsSettings";

const guidance = {
  github: "Use a fine-grained PAT scoped to Issues: Read & write.",
  jira: "Jira tokens cannot be scoped down further than the full account.",
  azure_devops: "Azure DevOps PATs are org-scoped, not project-scoped.",
};

beforeEach(() => {
  vi.mocked(fetchCredentials).mockResolvedValue({ credentials: [] });
  vi.mocked(fetchCredentialGuidance).mockResolvedValue({ guidance });
  vi.mocked(createCredential).mockReset();
  vi.mocked(deleteCredential).mockReset();
});

it("requires and submits the Jira account email", async () => {
  render(<IntegrationsSettings />);
  await screen.findByText(/fine-grained PAT/);
  fireEvent.click(screen.getByRole("button", { name: "Jira" }));
  fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Jira" } });
  fireEvent.change(screen.getByLabelText("Base URL"), {
    target: { value: "https://acme.atlassian.net" },
  });
  fireEvent.change(screen.getByLabelText("Personal Access Token"), {
    target: { value: "token" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Register Credential/ }));
  expect(createCredential).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Jira account email"), {
    target: { value: "dev@acme.test" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Register Credential/ }));

  await waitFor(() => {
    expect(createCredential).toHaveBeenCalledWith({
      provider: "jira",
      label: "Jira",
      baseUrl: "https://acme.atlassian.net",
      pat: "token",
      email: "dev@acme.test",
    });
  });
});

describe("IntegrationsSettings", () => {
  it("renders the empty state after loading", async () => {
    render(<IntegrationsSettings />);
    await waitFor(() => {
      expect(screen.getByText("No credentials registered yet.")).toBeInTheDocument();
    });
  });

  it("lists registered credentials without ever rendering a secret field", async () => {
    vi.mocked(fetchCredentials).mockResolvedValue({
      credentials: [
        {
          id: "cred-1",
          provider: "github",
          label: "My GitHub",
          baseUrl: "https://api.github.com",
          email: null,
          createdAt: "2026-01-01T00:00:00Z",
        },
      ],
    });

    render(<IntegrationsSettings />);
    await waitFor(() => {
      expect(screen.getByText("My GitHub")).toBeInTheDocument();
    });
    expect(screen.getByText("https://api.github.com")).toBeInTheDocument();
    expect(screen.queryByText(/^secret$|token value/i)).not.toBeInTheDocument();
  });

  it("never renders an OAuth or app-connection option (Story 3.5 AC3/NFR3)", async () => {
    render(<IntegrationsSettings />);
    await waitFor(() => {
      expect(screen.getByText(/fine-grained PAT/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/OAuth/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Personal Access Token")).toHaveAttribute("type", "password");
  });

  it("shows per-provider guidance and submits a new credential", async () => {
    vi.mocked(createCredential).mockResolvedValue({
      id: "cred-new",
      provider: "github",
      label: "New Cred",
      baseUrl: "https://api.github.com",
      email: null,
      createdAt: "2026-01-01T00:00:00Z",
    });

    render(<IntegrationsSettings />);
    await waitFor(() => {
      expect(screen.getByText(/fine-grained PAT/)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "New Cred" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://api.github.com" } });
    fireEvent.change(screen.getByLabelText("Personal Access Token"), { target: { value: "ghp_sentinel" } });
    fireEvent.click(screen.getByRole("button", { name: /Register Credential/ }));

    await waitFor(() => {
      expect(createCredential).toHaveBeenCalledWith({
        provider: "github",
        label: "New Cred",
        baseUrl: "https://api.github.com",
        pat: "ghp_sentinel",
        email: null,
      });
    });
  });

  it("blocks submission with a toast when required fields are missing", async () => {
    const { toast } = await import("sonner");

    render(<IntegrationsSettings />);
    await waitFor(() => {
      expect(fetchCredentials).toHaveBeenCalled();
    });

    fireEvent.click(screen.getByRole("button", { name: /Register Credential/ }));

    expect(createCredential).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("opens a confirm dialog and calls delete when confirmed", async () => {
    vi.mocked(fetchCredentials).mockResolvedValue({
      credentials: [
        {
          id: "cred-1",
          provider: "jira",
          label: "Jira Cred",
          baseUrl: "https://x.atlassian.net",
          email: "dev@example.com",
          createdAt: "2026-01-01T00:00:00Z",
        },
      ],
    });
    vi.mocked(deleteCredential).mockResolvedValue(undefined);

    render(<IntegrationsSettings />);
    await waitFor(() => {
      expect(screen.getByText("Jira Cred")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /Delete Jira Cred/ }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(deleteCredential).toHaveBeenCalledWith("cred-1");
    });
  });
});
