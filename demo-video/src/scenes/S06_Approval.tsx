/**
 * S06 — Cost + Scale: analytics scorecard cross-fading to dashboard completion.
 *
 * First half: analytics page with cost and model data.
 * Second half: quick cut back to the dashboard — our job has moved to "Completed"
 * column, closing the narrative loop.
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, SCENES, SCREENSHOT_STYLE } from "../constants";

const { fontFamily } = loadFont("normal", { weights: ["500", "600"] });

export const S06_CostScale: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.costScale;
  const half = Math.floor(dur * 0.55); // Slightly more time on analytics

  // Title
  const titleOpacity = interpolate(frame, [0, 15, 60, 80], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Analytics screenshot — first half
  const img1Opacity = interpolate(frame, [5, 25, half - 15, half], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const img1Scale = interpolate(frame, [5, half], [1.06, 1], { extrapolateRight: "clamp" });

  // Dashboard screenshot — second half (completion loop)
  const img2Opacity = interpolate(frame, [half - 5, half + 15], [0, 1], {
    extrapolateRight: "clamp",
  });
  const img2Scale = interpolate(frame, [half, dur], [1.04, 1], { extrapolateRight: "clamp" });

  // "Completed" badge overlay on dashboard
  const completedBadgeOpacity = interpolate(
    frame,
    [half + 40, half + 60],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

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
          Know what it costs.
        </h2>
      </div>

      {/* Analytics page */}
      <div
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          overflow: "hidden",
          opacity: img1Opacity,
        }}
      >
        <Img
          src={staticFile("captures/analytics-top.png")}
          style={{
            ...SCREENSHOT_STYLE,
            width: 3610,
            transform: `scale(${img1Scale})`,
          }}
        />
      </div>

      {/* Dashboard — completion loop */}
      <div
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          overflow: "hidden",
          opacity: img2Opacity,
        }}
      >
        <Img
          src={staticFile("captures/dashboard-desktop.png")}
          style={{
            ...SCREENSHOT_STYLE,
            width: 3610,
            transform: `scale(${img2Scale})`,
          }}
        />
      </div>

      {/* "Task completed" narrative closer */}
      <div
        style={{
          position: "absolute",
          bottom: 160,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          zIndex: 3,
          opacity: completedBadgeOpacity,
          pointerEvents: "none",
        }}
      >
        <div
          style={{
            background: "rgba(15, 17, 23, 0.9)",
            backdropFilter: "blur(20px)",
            border: `1px solid ${C.green}`,
            borderRadius: 16,
            padding: "20px 48px",
            display: "flex",
            alignItems: "center",
            gap: 20,
            fontSize: 36,
          }}
        >
          <span style={{ color: C.green, fontSize: 40 }}>✓</span>
          <span style={{ color: C.fg, fontWeight: 500 }}>
            Prompt to merged — one workflow
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
