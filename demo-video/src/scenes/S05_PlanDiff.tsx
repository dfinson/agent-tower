/**
 * S05 — Animated diff viewer: lines appear sequentially with green/red accents.
 */
import { AbsoluteFill, useCurrentFrame, interpolate, spring } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";
import { C, FPS, SCENES } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";

const { fontFamily } = loadFont("normal", { weights: ["400", "500"] });
const { fontFamily: monoFamily } = loadMono("normal", { weights: ["400"] });

type LT = "ctx" | "add" | "del";
interface DL { t: LT; c: string; n: number }

const LINES: DL[] = [
  { t: "ctx", c: '@router.get("/")', n: 8 },
  { t: "ctx", c: "async def list_tickets(", n: 9 },
  { t: "ctx", c: "    status: str | None = Query(None),", n: 10 },
  { t: "ctx", c: "    priority: str | None = Query(None),", n: 11 },
  { t: "del", c: "    limit: int = Query(20, ge=1, le=100),", n: 12 },
  { t: "del", c: "    offset: int = Query(0, ge=0),", n: 13 },
  { t: "add", c: '    limit: int = Query(20, ge=1, le=100, description="Max items per page"),', n: 12 },
  { t: "add", c: '    offset: int = Query(0, ge=0, description="Number of items to skip"),', n: 13 },
  { t: "ctx", c: "    svc: TicketService = Depends(),", n: 14 },
  { t: "del", c: ") -> list[Ticket]:", n: 15 },
  { t: "add", c: ") -> PaginatedResponse[Ticket]:", n: 15 },
  { t: "add", c: "    total = await svc.count_tickets(status=status, priority=priority)", n: 16 },
  { t: "add", c: "    items = await svc.list_tickets(", n: 17 },
  { t: "add", c: "        status=status, priority=priority, limit=limit, offset=offset", n: 18 },
  { t: "add", c: "    )", n: 19 },
  { t: "add", c: "    return PaginatedResponse(", n: 20 },
  { t: "add", c: "        items=items,", n: 21 },
  { t: "add", c: "        total=total,", n: 22 },
  { t: "add", c: "        limit=limit,", n: 23 },
  { t: "add", c: "        offset=offset,", n: 24 },
  { t: "add", c: "    )", n: 25 },
];

const LINE_H = 58;
const FPL = 8; // frames per line
const LS = 30; // line-start frame

const STYLE: Record<LT, { bg: string; fg: string; pfx: string; gutter: string }> = {
  ctx: { bg: "transparent", fg: "hsl(213 27% 75%)", pfx: " ", gutter: "hsl(215 12% 35%)" },
  add: { bg: "rgba(34,197,94,0.1)", fg: "#86efac", pfx: "+", gutter: "#22c55e" },
  del: { bg: "rgba(239,68,68,0.1)", fg: "#fca5a5", pfx: "-", gutter: "#ef4444" },
};

export const S05_PlanDiff: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.planDiff;

  const cEntry = spring({ frame, fps: FPS, config: { damping: 100, stiffness: 70 }, durationInFrames: 35 });
  const cScale = interpolate(cEntry, [0, 1], [0.92, 1]);
  const cOp = interpolate(frame, [5, 30], [0, 1], { extrapolateRight: "clamp" });

  // Scroll (only when content overflows)
  const totalH = LINES.length * LINE_H;
  const visH = 1650;
  const maxScr = Math.max(0, totalH - visH + 60);
  const scrY = (() => {
    if (maxScr <= 0) return 0;
    const s = LS + Math.floor(visH / LINE_H) * FPL;
    const e = LS + LINES.length * FPL;
    if (s >= e) return 0;
    return interpolate(frame, [s, e], [0, maxScr], {
      extrapolateLeft: "clamp", extrapolateRight: "clamp",
    });
  })();

  const statsOp = interpolate(frame, [15, 40], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [dur - 15, dur], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily, opacity: fadeOut }}>
      <AnimatedBg seed={4} intensity={0.3} />

      <div style={{
        position: "absolute", left: "50%", top: "50%",
        transform: `translate(-50%,-50%) scale(${cScale})`,
        width: 3200, height: 1900, borderRadius: 24, overflow: "hidden",
        opacity: cOp,
        boxShadow: "0 60px 160px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.08)",
      }}>
        {/* Editor header */}
        <div style={{
          height: 80,
          background: "linear-gradient(180deg, hsl(215 22% 16%), hsl(215 22% 12%))",
          display: "flex", alignItems: "center", padding: "0 32px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}>
          <div style={{ display: "flex", gap: 10, marginRight: 24 }}>
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#ff5f57" }} />
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#febc2e" }} />
            <div style={{ width: 14, height: 14, borderRadius: "50%", background: "#28c840" }} />
          </div>
          <div style={{
            background: C.bg, padding: "10px 24px", borderRadius: "8px 8px 0 0",
            fontSize: 24, fontFamily: monoFamily, color: C.fg, borderTop: `2px solid ${C.primary}`,
          }}>src/routes/tickets.py</div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 16, opacity: statsOp }}>
            <span style={{ fontSize: 22, color: "#22c55e" }}>+12</span>
            <span style={{ fontSize: 22, color: "#ef4444" }}>−3</span>
          </div>
        </div>

        {/* Diff lines */}
        <div style={{ background: C.bg, height: 1900 - 80, overflow: "hidden", position: "relative" }}>
          <div style={{ transform: `translateY(${-scrY}px)`, padding: "16px 0" }}>
            {LINES.map((l, i) => {
              const lf = LS + i * FPL;
              const p = spring({ frame: Math.max(0, frame - lf), fps: FPS, config: { damping: 80, stiffness: 150 }, durationInFrames: 12 });
              if (frame < lf) return null;
              const sx = l.t === "add" ? interpolate(p, [0, 1], [60, 0]) : 0;
              const s = STYLE[l.t];
              return (
                <div key={i} style={{
                  height: LINE_H, display: "flex", alignItems: "center",
                  background: s.bg, opacity: p, transform: `translateX(${sx}px)`,
                  fontFamily: monoFamily, fontSize: 26,
                  borderLeft: l.t !== "ctx" ? `4px solid ${s.gutter}` : "4px solid transparent",
                }}>
                  <span style={{ width: 80, textAlign: "right", paddingRight: 20, color: s.gutter, fontSize: 22 }}>{l.n}</span>
                  <span style={{ width: 30, color: s.gutter, fontWeight: "bold" }}>{s.pfx}</span>
                  <span style={{
                    color: s.fg,
                    textDecoration: l.t === "del" && p > 0.8 ? "line-through" : "none",
                    textDecorationColor: "rgba(239,68,68,0.5)",
                  }}>{l.c}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
