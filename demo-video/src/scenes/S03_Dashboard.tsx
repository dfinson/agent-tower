/**
 * S03 — Dashboard reveal: screenshot in a 3-D rotating browser frame.
 */
import {
  AbsoluteFill,
  Img,
  staticFile,
  useCurrentFrame,
  interpolate,
  spring,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, FPS, SCENES } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";
import { BrowserFrame } from "../components/BrowserFrame";

const { fontFamily } = loadFont("normal", { weights: ["500"] });

export const S03_Dashboard: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.dashboard;

  // Title
  const titleOpacity = interpolate(frame, [0, 15, 60, 80], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(frame, [0, 15], [30, 0], { extrapolateRight: "clamp" });

  // Card entrance — spring scale
  const cardEntry = spring({
    frame: Math.max(0, frame - 10),
    fps: FPS,
    config: { damping: 80, stiffness: 60 },
    durationInFrames: 40,
  });
  const cardScale = interpolate(cardEntry, [0, 1], [0.88, 1]);
  const cardOpacity = interpolate(frame, [10, 35], [0, 1], { extrapolateRight: "clamp" });

  // Gentle continuous 3-D rotation
  const rotateY = interpolate(frame, [30, dur], [-2.5, 2.5], { extrapolateRight: "clamp" });
  const rotateX = interpolate(frame, [30, dur], [3, -1], { extrapolateRight: "clamp" });

  // Float
  const floatY = Math.sin(frame * 0.015) * 5;

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily }}>
      <AnimatedBg seed={2} intensity={0.4} />

      {/* Title */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          zIndex: 2,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
        }}
      >
        <h2
          style={{
            fontSize: 72,
            fontWeight: 500,
            color: C.white,
            textShadow: "0 4px 60px rgba(0,0,0,0.9)",
            letterSpacing: "-0.02em",
          }}
        >
          See everything. Across every agent.
        </h2>
      </div>

      {/* Screenshot in floating browser frame */}
      <div style={{ position: "absolute", inset: 0, transform: `translateY(${floatY}px)` }}>
        <BrowserFrame
          rotateX={rotateX}
          rotateY={rotateY}
          scale={cardScale}
          opacity={cardOpacity}
          width="86%"
        >
          <Img
            src={staticFile("captures/dashboard-desktop.png")}
            style={{ width: "100%", display: "block" }}
          />
        </BrowserFrame>
      </div>
    </AbsoluteFill>
  );
};
