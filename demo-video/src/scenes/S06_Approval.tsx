/**
 * S06 — Approval click video in a floating 3-D browser frame.
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

export const S06_Approval: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.approval;

  const bgOp = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });
  const entry = spring({
    frame,
    fps: FPS,
    config: { damping: 100, stiffness: 90 },
    durationInFrames: 20,
  });
  const fScale = entry * 0.12 + 0.88;
  const fRotateX = interpolate(frame, [0, 20], [3, 0], { extrapolateRight: "clamp" });
  const fOp = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const floatY = Math.sin(frame * 0.025) * 4;
  const fadeOut = interpolate(frame, [dur - 10, dur], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, opacity: fadeOut }}>
      <div style={{ opacity: bgOp, position: "absolute", inset: 0 }}>
        <AnimatedBg seed={5} intensity={0.45} />
      </div>
      <div style={{ position: "absolute", inset: 0, transform: `translateY(${floatY}px)` }}>
        <BrowserFrame rotateX={fRotateX} scale={fScale} opacity={fOp} width="78%">
          <div style={{ overflow: "hidden", position: "relative" }}>
            <OffthreadVideo
              src={staticFile("captures/video-approval-click.webm")}
              startFrom={30}
              style={{ width: "180%", marginLeft: "-12%", marginBottom: "-45%", display: "block" }}
            />
            <div style={{
              position: "absolute", top: 0, right: 0, bottom: 0, width: "55%",
              background: "linear-gradient(90deg, transparent 0%, hsl(220 20% 7% / 0.6) 30%, hsl(220 20% 7%) 55%)",
              pointerEvents: "none",
            }} />
            <div style={{
              position: "absolute", left: 0, right: 0, bottom: 0, height: "30%",
              background: "linear-gradient(180deg, transparent 0%, hsl(220 20% 7%) 60%)",
              pointerEvents: "none",
            }} />
          </div>
        </BrowserFrame>
      </div>
    </AbsoluteFill>
  );
};
