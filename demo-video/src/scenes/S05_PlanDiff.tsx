/**
 * S05 — Review: diff viewer with slow pan through changes.
 *
 * Shows the diff viewer screenshot. The camera slowly pans downward through
 * the code changes, simulating a developer scrolling through the diff.
 * Title overlay + "Merge" button highlight at the end.
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, SCENES, SCREENSHOT_STYLE } from "../constants";

const { fontFamily } = loadFont("normal", { weights: ["500", "600"] });

export const S05_Review: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.review;

  // Title
  const titleOpacity = interpolate(frame, [0, 15, 75, 95], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Screenshot fades in and slowly pans down to reveal more of the diff
  const imgOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });
  const imgScale = interpolate(frame, [0, dur], [1.15, 1.25], { extrapolateRight: "clamp" });
  // Slow downward pan — simulates scrolling through the diff
  const imgY = interpolate(frame, [30, dur - 60], [0, -180], { extrapolateRight: "clamp" });

  // File count badge slides in
  const badgeOpacity = interpolate(frame, [100, 120], [0, 1], { extrapolateRight: "clamp" });

  // "Merge" button glow near end
  const mergeGlow = interpolate(frame, [dur - 90, dur - 60, dur - 20], [0, 1, 0.6], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily }}>
      {/* Title */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          zIndex: 2,
          pointerEvents: "none",
          opacity: titleOpacity,
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
          Review every change before it lands.
        </h2>
      </div>

      {/* Diff screenshot with pan effect */}
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
        <Img
          src={staticFile("captures/job-diff.png")}
          style={{
            ...SCREENSHOT_STYLE,
            width: 3610,
            transform: `scale(${imgScale}) translateY(${imgY}px)`,
            transformOrigin: "center 35%",
          }}
        />
      </div>

      {/* File stats badge */}
      <div
        style={{
          position: "absolute",
          bottom: 120,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          zIndex: 3,
          opacity: badgeOpacity,
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            background: "rgba(15, 17, 23, 0.85)",
            backdropFilter: "blur(20px)",
            border: `1px solid ${C.border}`,
            borderRadius: 16,
            padding: "20px 48px",
            display: "flex",
            alignItems: "center",
            gap: 32,
            fontSize: 36,
          }}
        >
          <span style={{ color: C.fg, fontWeight: 500 }}>4 files</span>
          <span style={{ color: C.green, fontWeight: 600 }}>+80</span>
          <span style={{ color: "#ef4444", fontWeight: 600 }}>-3</span>
        </div>
      </div>

      {/* Merge button glow (top-right area where Merge button lives in UI) */}
      <div
        style={{
          position: "absolute",
          top: 190,
          right: 360,
          width: 180,
          height: 64,
          borderRadius: 12,
          boxShadow: `0 0 ${50 * mergeGlow}px ${20 * mergeGlow}px rgba(34, 197, 94, ${0.4 * mergeGlow})`,
          zIndex: 4,
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};
