/**
 * S07 — Analytics: animated score cards, growing bars, trend chart.
 */
import { AbsoluteFill, useCurrentFrame, interpolate, spring } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, FPS, SCENES } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";

const { fontFamily } = loadFont("normal", { weights: ["400", "500", "600", "700"] });

const CARDS = [
  { label: "Total Jobs", val: 42, color: C.primary },
  { label: "Merged", val: 28, color: "#22c55e" },
  { label: "Total Cost", val: 43.28, prefix: "$", dec: 2, color: "#f59e0b" },
  { label: "Merge Rate", val: 80, suffix: "%", color: "#8b5cf6" },
];

const BARS = [
  { label: "Sonnet 4.6 (Copilot)", jobs: 20, cost: "$13.00", pct: 100, color: "#8534F3" },
  { label: "Sonnet 4.6 (Claude)", jobs: 14, cost: "$20.72", pct: 70, color: "#D97757" },
  { label: "Haiku 4.5 (Claude)", jobs: 8, cost: "$4.14", pct: 40, color: "#3b82f6" },
];

const TREND = [4.2, 6.8, 5.1, 8.4, 7.2, 6.9, 4.6];
const MAX_TREND = Math.max(...TREND);
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export const S07_Analytics: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.analytics;

  const titleOp = interpolate(frame, [0, 15, 55, 70], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const containerOp = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [dur - 15, dur], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily, opacity: fadeOut }}>
      <AnimatedBg seed={6} intensity={0.35} />

      {/* Title */}
      <div style={{
        position: "absolute", top: 60, left: 0, right: 0,
        display: "flex", justifyContent: "center", zIndex: 2, opacity: titleOp,
      }}>
        <h2 style={{
          fontSize: 64, fontWeight: 500, color: C.white,
          textShadow: "0 4px 40px rgba(0,0,0,0.9)", letterSpacing: "-0.02em",
          textAlign: "center", lineHeight: 1.4,
        }}>
          Know what it costs{"\n"}and what it{"'"}s worth.
        </h2>
      </div>

      {/* Content */}
      <div style={{
        position: "absolute", left: "50%", top: "50%",
        transform: "translate(-50%,-48%)", width: 3400,
        opacity: containerOp, display: "flex", flexDirection: "column", gap: 48,
      }}>
        {/* Score cards */}
        <div style={{ display: "flex", gap: 36, justifyContent: "center" }}>
          {CARDS.map((cd, i) => {
            const cf = 20 + i * 12;
            const p = spring({ frame: Math.max(0, frame - cf), fps: FPS, config: { damping: 80, stiffness: 100 }, durationInFrames: 30 });
            const cY = interpolate(p, [0, 1], [40, 0]);
            const numP = interpolate(frame, [cf + 15, cf + 60], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            const display = cd.dec
              ? (cd.val * numP).toFixed(cd.dec)
              : Math.round(cd.val * numP).toString();
            return (
              <div key={i} style={{
                flex: 1, background: C.card, borderRadius: 20, padding: "36px 44px",
                opacity: p, transform: `translateY(${cY}px)`,
                boxShadow: "0 8px 40px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.06)",
              }}>
                <p style={{ fontSize: 28, color: C.muted, margin: "0 0 12px" }}>{cd.label}</p>
                <span style={{
                  fontSize: 80, fontWeight: 700, color: cd.color,
                  fontVariantNumeric: "tabular-nums",
                }}>
                  {cd.prefix ?? ""}{display}{cd.suffix ?? ""}
                </span>
              </div>
            );
          })}
        </div>

        {/* Model comparison bars */}
        <div style={{
          background: C.card, borderRadius: 20, padding: "36px 44px",
          boxShadow: "0 8px 40px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.06)",
        }}>
          <p style={{ fontSize: 30, color: C.fg, margin: "0 0 28px", fontWeight: 500 }}>
            Jobs by Model
          </p>
          {BARS.map((b, i) => {
            const bf = 100 + i * 20;
            const bp = interpolate(frame, [bf, bf + 40], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            const lOp = interpolate(frame, [bf, bf + 15], [0, 1], {
              extrapolateLeft: "clamp", extrapolateRight: "clamp",
            });
            return (
              <div key={i} style={{ display: "flex", alignItems: "center", marginBottom: 24, gap: 24 }}>
                <span style={{ width: 500, fontSize: 26, color: C.fg, textAlign: "right", opacity: lOp }}>
                  {b.label}
                </span>
                <div style={{
                  flex: 1, height: 40, background: "rgba(255,255,255,0.04)",
                  borderRadius: 8, overflow: "hidden",
                }}>
                  <div style={{
                    width: `${b.pct * bp}%`, height: "100%",
                    background: `linear-gradient(90deg, ${b.color}, ${b.color}cc)`,
                    borderRadius: 8, boxShadow: `0 0 20px ${b.color}33`,
                  }} />
                </div>
                <span style={{ width: 150, fontSize: 24, color: C.muted, opacity: lOp }}>{b.cost}</span>
              </div>
            );
          })}
        </div>

        {/* Cost trend */}
        <div style={{
          background: C.card, borderRadius: 20, padding: "36px 44px",
          boxShadow: "0 8px 40px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.06)",
        }}>
          <p style={{ fontSize: 30, color: C.fg, margin: "0 0 28px", fontWeight: 500 }}>
            7-Day Cost Trend
          </p>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 24, height: 180 }}>
            {TREND.map((cost, i) => {
              const tf = 180 + i * 12;
              const tp = spring({ frame: Math.max(0, frame - tf), fps: FPS, config: { damping: 60, stiffness: 100 }, durationInFrames: 20 });
              const h = (cost / MAX_TREND) * 160 * Math.max(0, tp);
              return (
                <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
                  <div style={{
                    width: "100%", height: h,
                    background: `linear-gradient(180deg, ${C.primary} 0%, ${C.primary}66 100%)`,
                    borderRadius: "8px 8px 4px 4px", boxShadow: `0 0 20px ${C.primary}22`,
                  }} />
                  <span style={{ fontSize: 20, color: C.muted }}>{DAYS[i]}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
