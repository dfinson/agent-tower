/**
 * S02 — Scale Reveal: camera pulls back to show the full Kanban dashboard.
 *
 * Starts zoomed in (as if we just launched from the new-job dialog), then
 * slowly zooms out to reveal the full board with 9+ jobs in mixed states.
 * Title overlay fades in/out while the screenshot is revealed.
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, SCENES, SCREENSHOT_STYLE } from "../constants";

const { fontFamily } = loadFont("normal", { weights: ["500"] });

export const S02_ScaleReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.scaleReveal;

  // Screenshot starts zoomed and slowly zooms out
  const imgScale = interpolate(frame, [0, dur], [1.25, 1], { extrapolateRight: "clamp" });
  const imgOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  // Gentle upward pan as we zoom out
  const imgY = interpolate(frame, [0, dur], [-80, 0], { extrapolateRight: "clamp" });

  // Title overlay
  const titleOpacity = interpolate(frame, [15, 35, 100, 120], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(frame, [15, 35], [20, 0], { extrapolateRight: "clamp" });

  // Subtle "new job" highlight glow on one card (bottom-left area)
  const glowOpacity = interpolate(frame, [5, 25, 80, 100], [0, 0.7, 0.7, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily }}>
      {/* Title overlay */}
      <div
        style={{
          position: "absolute",
          top: 120,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          zIndex: 2,
          pointerEvents: "none",
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
        }}
      >
        <h2
          style={{
            fontSize: 72,
            fontWeight: 500,
            color: C.white,
            textShadow: "0 4px 40px rgba(0,0,0,0.95), 0 2px 10px rgba(0,0,0,0.8)",
            letterSpacing: "-0.02em",
          }}
        >
          One view. Every agent. Every repo.
        </h2>
      </div>

      {/* Dashboard screenshot */}
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          overflow: "hidden",
          opacity: imgOpacity,
        }}
      >
        <div style={{ position: "relative" }}>
          <Img
            src={staticFile("captures/dashboard-desktop.png")}
            style={{
              ...SCREENSHOT_STYLE,
              width: 3610, // 94% of 3840
              transform: `scale(${imgScale}) translateY(${imgY}px)`,
              transformOrigin: "center 30%",
            }}
          />
          {/* Glow highlight on the new job area */}
          <div
            style={{
              position: "absolute",
              bottom: "35%",
              left: "5%",
              width: 500,
              height: 200,
              borderRadius: 20,
              boxShadow: `0 0 80px 20px rgba(74, 138, 245, 0.3)`,
              opacity: glowOpacity,
              pointerEvents: "none",
              transform: `scale(${imgScale}) translateY(${imgY}px)`,
              transformOrigin: "center 30%",
            }}
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};
