/**
 * S03 — Supervise: live transcript streaming simulation.
 *
 * Shows the job detail page with transcript lines appearing one by one,
 * simulating the real-time streaming experience. This is the "motion = credibility"
 * beat — proving the product actually works by showing live text appearing.
 *
 * Uses the real job-running-live screenshot as background, then overlays
 * simulated streaming transcript content on top.
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, SCENES, SCREENSHOT_STYLE } from "../constants";

const { fontFamily } = loadFont("normal", { weights: ["400", "500"] });

export const S03_Supervise: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.supervise;

  // Title overlay (brief)
  const titleOpacity = interpolate(frame, [0, 15, 70, 90], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Screenshot visible full time, starts slightly zoomed
  const imgScale = interpolate(frame, [0, dur], [1.08, 1.18], { extrapolateRight: "clamp" });
  const imgY = interpolate(frame, [0, dur], [0, -200], { extrapolateRight: "clamp" });
  const imgOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });

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
          zIndex: 3,
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
          Watch it think. Watch it build.
        </h2>
      </div>

      {/* Job detail screenshot — slowly zooms into transcript area */}
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
          src={staticFile("captures/job-running-live.png")}
          style={{
            ...SCREENSHOT_STYLE,
            width: 3610,
            transform: `scale(${imgScale}) translateY(${imgY}px)`,
            transformOrigin: "center 55%",
          }}
        />
      </div>


    </AbsoluteFill>
  );
};
