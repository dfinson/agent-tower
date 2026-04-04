/**
 * S08 — CTA: Logo + pip install + GitHub URL.
 *
 * Clean, actionable closing. No fluff.
 * Staggered reveal: logo → tagline → install command → GitHub URL.
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { loadFont as loadMono } from "@remotion/google-fonts/RobotoMono";
import { C, SCENES } from "../constants";

const { fontFamily } = loadFont("normal", { weights: ["400", "600"] });
const { fontFamily: monoFamily } = loadMono("normal", { weights: ["400"], subsets: ["latin"] });

export const S08_CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.cta;

  // Logo
  const logoOpacity = interpolate(frame, [0, 25], [0, 1], { extrapolateRight: "clamp" });
  const logoScale = interpolate(frame, [0, 25], [0.9, 1], { extrapolateRight: "clamp" });

  // Tagline
  const tagOpacity = interpolate(frame, [30, 50], [0, 1], { extrapolateRight: "clamp" });
  const tagY = interpolate(frame, [30, 50], [15, 0], { extrapolateRight: "clamp" });

  // Install command
  const cmdOpacity = interpolate(frame, [55, 75], [0, 1], { extrapolateRight: "clamp" });
  const cmdY = interpolate(frame, [55, 75], [15, 0], { extrapolateRight: "clamp" });

  // GitHub URL
  const urlOpacity = interpolate(frame, [80, 100], [0, 1], { extrapolateRight: "clamp" });

  // "Open source" badge
  const badgeOpacity = interpolate(frame, [95, 115], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.bg,
        justifyContent: "center",
        alignItems: "center",
        fontFamily,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 50 }}>
        {/* Logo */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 40,
            opacity: logoOpacity,
            transform: `scale(${logoScale})`,
          }}
        >
          <Img src={staticFile("mark.png")} style={{ width: 120, height: 120 }} />
          <span style={{ fontSize: 80, fontWeight: 600, color: C.white, letterSpacing: "-0.02em" }}>
            CodePlane
          </span>
        </div>

        {/* Tagline */}
        <p
          style={{
            fontSize: 44,
            color: C.muted,
            textAlign: "center",
            opacity: tagOpacity,
            transform: `translateY(${tagY}px)`,
            margin: 0,
          }}
        >
          A control plane for your coding agents.
        </p>

        {/* Install command */}
        <div
          style={{
            opacity: cmdOpacity,
            transform: `translateY(${cmdY}px)`,
            marginTop: 20,
          }}
        >
          <div
            style={{
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 16,
              padding: "24px 56px",
              display: "flex",
              alignItems: "center",
              gap: 20,
            }}
          >
            <span style={{ fontSize: 36, color: C.muted, fontFamily: monoFamily }}>$</span>
            <span style={{ fontSize: 36, color: C.fg, fontFamily: monoFamily }}>
              pip install codeplane
            </span>
          </div>
        </div>

        {/* GitHub URL */}
        <p
          style={{
            fontSize: 38,
            color: C.primary,
            fontWeight: 600,
            letterSpacing: "0.02em",
            opacity: urlOpacity,
            margin: 0,
            marginTop: 10,
          }}
        >
          github.com/dfinson/codeplane
        </p>

        {/* Open source badge */}
        <div
          style={{
            opacity: badgeOpacity,
            display: "flex",
            alignItems: "center",
            gap: 16,
          }}
        >
          <span
            style={{
              fontSize: 30,
              color: C.green,
              fontWeight: 600,
              border: `1px solid ${C.green}`,
              borderRadius: 12,
              padding: "8px 24px",
              letterSpacing: "0.03em",
            }}
          >
            Open Source
          </span>
          <span style={{ fontSize: 30, color: C.muted }}>
            MIT License
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
