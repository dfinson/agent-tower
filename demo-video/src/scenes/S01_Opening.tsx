/**
 * S01 — Cold Open: job-creation video in a floating 3-D browser frame.
 */
import {
  AbsoluteFill,
  OffthreadVideo,
  staticFile,
  useCurrentFrame,
  interpolate,
  spring,
} from "remotion";
import { FPS, SCENES, C } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";
import { BrowserFrame } from "../components/BrowserFrame";

export const S01_Opening: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.opening;

  // Background fade-in
  const bgOpacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });

  // Frame entrance — spring scale + tilt
  const entry = spring({
    frame,
    fps: FPS,
    config: { damping: 100, stiffness: 80 },
    durationInFrames: 30,
  });
  const frameScale = entry * 0.15 + 0.85;
  const frameRotateX = interpolate(frame, [0, 30], [4, 0], { extrapolateRight: "clamp" });
  const frameOpacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });

  // Continuous subtle float
  const floatY = Math.sin(frame * 0.02) * 4;

  // Fade out
  const fadeOut = interpolate(frame, [dur - 12, dur], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, opacity: fadeOut }}>
      <div style={{ opacity: bgOpacity, position: "absolute", inset: 0 }}>
        <AnimatedBg seed={0} intensity={0.5} />
      </div>
      <div style={{ position: "absolute", inset: 0, transform: `translateY(${floatY}px)` }}>
        <BrowserFrame
          rotateX={frameRotateX}
          scale={frameScale}
          opacity={frameOpacity}
          width="78%"
        >
          <div style={{ overflow: "hidden", position: "relative" }}>
            <OffthreadVideo
              src={staticFile("captures/video-job-creation.webm")}
              startFrom={30}
              style={{ width: "180%", marginLeft: "-12%", marginBottom: "-50%", display: "block" }}
            />
            {/* Gradient overlays to mask empty page areas */}
            <div style={{
              position: "absolute", top: 0, right: 0, bottom: 0, width: "55%",
              background: "linear-gradient(90deg, transparent 0%, hsl(220 20% 7% / 0.6) 30%, hsl(220 20% 7%) 55%)",
              pointerEvents: "none",
            }} />
            <div style={{
              position: "absolute", left: 0, right: 0, bottom: 0, height: "35%",
              background: "linear-gradient(180deg, transparent 0%, hsl(220 20% 7%) 60%)",
              pointerEvents: "none",
            }} />
          </div>
        </BrowserFrame>
      </div>
    </AbsoluteFill>
  );
};
