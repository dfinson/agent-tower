import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PromptWithVoice } from "../VoiceButton";

vi.mock("../../api/client", () => ({
  transcribeAudio: vi.fn(),
}));

vi.mock("../../hooks/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("../ui/tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("wavesurfer.js", () => ({
  default: {
    create: vi.fn(() => ({
      destroy: vi.fn(),
    })),
  },
}));

vi.mock("wavesurfer.js/dist/plugins/record.esm.js", () => ({
  default: {
    create: vi.fn(() => ({
      on: vi.fn(),
      destroy: vi.fn(),
      startRecording: vi.fn(),
      stopRecording: vi.fn(),
    })),
  },
}));

describe("PromptWithVoice", () => {
  it("renders a voice input control next to the prompt textarea", () => {
    render(<PromptWithVoice value="" onChange={() => {}} />);

    expect(screen.getByLabelText("Voice input")).toBeInTheDocument();
  });
});