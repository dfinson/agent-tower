/**
 * S02 — Problem statement with animated reveal + gradient accent line.
 */
import { AbsoluteFill, useCurrentFrame, interpolate, spring } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, FPS, SCENES } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";

const { fontFamily } = loadFont("normal", { weights: ["300", "700"], subsets: ["latin"] });

export const S02_Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.problem;

  // Main headline — spring up
  const headEntry = spring({
    frame,
    fps: FPS,
    config: { damping: 80, stiffness: 100 },
    durationInFrames: 25,
  });
  const headY = interpolate(headEntry, [0, 1], [60, 0]);

  // Accent gradient line
  const lineW = interpolate(frame, [10, 45], [0, 500], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Sub-text
  const subEntry = spring({
    frame: Math.max(0, frame - 25),
    fps: FPS,
    config: { damping: 80, stiffness: 100 },
    durationInFrames: 20,
  });
  const subY = interpolate(subEntry, [0, 1], [30, 0]);

  const fadeOut = interpolate(frame, [dur - 10, dur], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily, opacity: fadeOut }}>
      <AnimatedBg seed={1} intensity={0.3} />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          zIndex: 1,
        }}
      >
        <h1
          style={{
            fontSize: 92,
            fontWeight: 700,
            color: C.white,
            letterSpacing: "-0.03em",
            margin: 0,
            opacity: headEntry,
            transform: `translateY(${headY}px)`,
          }}
        >
          Every coding agent is a black box.
        </h1>
        <div
          style={{
            width: lineW,
            height: 3,
            background: `linear-gradient(90deg, transparent, ${C.primary}, transparent)`,
            marginTop: 36,
            marginBottom: 36,
            borderRadius: 2,
          }}
        />
        <p
          style={{
            fontSize: 46,
            fontWeight: 300,
            color: C.muted,
            margin: 0,
            opacity: subEntry,
            transform: `translateY(${subY}px)`,
          }}
        >
          Scattered terminals. Zero shared context.
        </p>
      </div>
    </AbsoluteFill>
  );
};
