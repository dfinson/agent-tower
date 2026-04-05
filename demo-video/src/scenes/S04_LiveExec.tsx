/**
 * S04 — Live execution: animated rolling transcript with tool calls.
 */
import { AbsoluteFill, useCurrentFrame, interpolate, spring } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";
import { C, FPS, SCENES } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";

const { fontFamily } = loadFont("normal", { weights: ["400", "500", "600"] });
const { fontFamily: monoFamily } = loadMono("normal", { weights: ["400"] });

type Kind = "reasoning" | "tool" | "agent";
interface Entry { kind: Kind; text: string; detail?: string; tool?: string }

const ENTRIES: Entry[] = [
  { kind: "reasoning", text: "I need to understand the existing ticket list endpoint before adding email search..." },
  { kind: "tool", tool: "read_file", text: "Read src/routes/tickets.py L1-80" },
  { kind: "tool", tool: "read_file", text: "Read src/services/ticket_service.py L1-60" },
  { kind: "tool", tool: "grep_search", text: 'Search "customer_email|email" in src/**/*.py', detail: "2 matches found" },
  { kind: "agent", text: "Analyzed codebase. Ticket model has customer_email. Adding email query param, updating service, writing tests." },
  { kind: "reasoning", text: "I'll use ilike for case-insensitive partial matching on email addresses." },
  { kind: "tool", tool: "edit_file", text: "Edit src/routes/tickets.py — add email parameter" },
  { kind: "tool", tool: "edit_file", text: "Edit src/services/ticket_service.py — add ilike filter" },
  { kind: "tool", tool: "terminal", text: "$ pytest tests/ -x --tb=short", detail: "14 passed in 2.34s ✓" },
  { kind: "agent", text: "Email filter implemented with case-insensitive partial matching. All existing tests pass." },
  { kind: "tool", tool: "create_file", text: "Create tests/test_email_search.py" },
  { kind: "tool", tool: "terminal", text: "$ pytest tests/test_email_search.py -v", detail: "5 passed in 1.87s ✓" },
];

const ENTRY_H = 130;
const VISIBLE_H = 1700;
const HEADER_H = 80;
const GAP = 18;
const ENTRY_START = 20;

const COLORS: Record<Kind, { border: string; badge: string; bg: string }> = {
  reasoning: { border: "#a78bfa", badge: "#7c3aed", bg: "rgba(124,58,237,0.08)" },
  tool:      { border: "#3b82f6", badge: "#2563eb", bg: "rgba(37,99,235,0.08)" },
  agent:     { border: "#22c55e", badge: "#16a34a", bg: "rgba(22,163,74,0.08)" },
};
const LABELS: Record<Kind, string> = { reasoning: "Thinking", tool: "Tool", agent: "Agent" };

export const S04_LiveExec: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.liveExecution;

  const containerOp = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const containerS = spring({ frame, fps: FPS, config: { damping: 100, stiffness: 80 }, durationInFrames: 25 }) * 0.08 + 0.92;

  const titleOp = interpolate(frame, [0, 15, 50, 65], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // Auto-scroll
  const totalH = ENTRIES.length * (ENTRY_H + 16);
  const maxScroll = Math.max(0, totalH - VISIBLE_H + 100);
  const scrollStart = ENTRY_START + Math.floor(VISIBLE_H / (ENTRY_H + 16)) * GAP;
  const scrollEnd = ENTRY_START + ENTRIES.length * GAP;
  const scrollY = interpolate(frame, [scrollStart, scrollEnd], [0, maxScroll], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  const cursorOn = Math.floor(frame / 12) % 2 === 0;
  const fadeOut = interpolate(frame, [dur - 15, dur], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily, opacity: fadeOut }}>
      <AnimatedBg seed={3} intensity={0.3} />

      {/* Title */}
      <div style={{
        position: "absolute", top: 50, left: 0, right: 0,
        display: "flex", justifyContent: "center", zIndex: 2, opacity: titleOp,
      }}>
        <h2 style={{
          fontSize: 64, fontWeight: 500, color: C.white,
          textShadow: "0 4px 40px rgba(0,0,0,0.9)", letterSpacing: "-0.02em",
        }}>
          Watch it think. Watch it build.
        </h2>
      </div>

      {/* Terminal card */}
      <div style={{
        position: "absolute", left: "50%", top: "50%",
        transform: `translate(-50%,-50%) scale(${containerS})`,
        width: 3000, height: 1850, borderRadius: 24, overflow: "hidden",
        opacity: containerOp,
        boxShadow: "0 60px 160px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.08)",
      }}>
        {/* Header */}
        <div style={{
          height: HEADER_H,
          background: "linear-gradient(180deg, hsl(215 22% 16%) 0%, hsl(215 22% 12%) 100%)",
          display: "flex", alignItems: "center", padding: "0 32px", gap: 16,
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}>
          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#febc2e" }} />
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#28c840" }} />
          </div>
          <div style={{ marginLeft: 20, fontSize: 26, color: C.fg, fontFamily: monoFamily, display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{
              background: "rgba(34,197,94,0.15)", color: "#22c55e",
              padding: "4px 12px", borderRadius: 6, fontSize: 22,
            }}>Running</span>
            <span>customer-email-search</span>
          </div>
        </div>

        {/* Entries */}
        <div style={{ background: C.bg, height: 1850 - HEADER_H, overflow: "hidden", position: "relative" }}>
          <div style={{ transform: `translateY(${-scrollY}px)`, padding: "24px 32px" }}>
            {ENTRIES.map((e, i) => {
              const ef = ENTRY_START + i * GAP;
              const p = spring({ frame: Math.max(0, frame - ef), fps: FPS, config: { damping: 80, stiffness: 120 }, durationInFrames: 15 });
              if (frame < ef) return null;
              const slideX = interpolate(p, [0, 1], [40, 0]);
              const c = COLORS[e.kind];
              return (
                <div key={i} style={{
                  opacity: p, transform: `translateX(${slideX}px)`, marginBottom: 16,
                  padding: "16px 24px", borderLeft: `4px solid ${c.border}`,
                  background: c.bg, borderRadius: "0 12px 12px 0",
                  display: "flex", flexDirection: "column", gap: 8,
                }}>
                  <span style={{
                    alignSelf: "flex-start",
                    background: c.badge, color: "#fff", padding: "4px 14px",
                    borderRadius: 6, fontSize: 22, fontWeight: 600,
                    textTransform: "uppercase", letterSpacing: "0.05em",
                  }}>
                    {LABELS[e.kind]}{e.tool ? ` · ${e.tool}` : ""}
                  </span>
                  <p style={{
                    fontSize: 28, margin: 0, lineHeight: 1.5,
                    color: e.kind === "reasoning" ? C.muted : C.fg,
                    fontStyle: e.kind === "reasoning" ? "italic" : "normal",
                    fontFamily: e.kind === "tool" ? monoFamily : fontFamily,
                  }}>{e.text}</p>
                  {e.detail && (
                    <p style={{
                      fontSize: 24, margin: 0, fontFamily: monoFamily,
                      color: e.detail.includes("✓") ? "#22c55e" : C.muted,
                    }}>{e.detail}</p>
                  )}
                </div>
              );
            })}
            {/* Blinking cursor */}
            <div style={{ marginTop: 16, opacity: cursorOn ? 0.7 : 0 }}>
              <div style={{ width: 3, height: 32, background: C.primary, borderRadius: 2 }} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
