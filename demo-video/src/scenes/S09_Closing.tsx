/**
 * S09 — Closing: logo + tagline + URL with animated background.
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

const { fontFamily } = loadFont("normal", { weights: ["400", "600"] });

export const S09_Closing: React.FC = () => {
  const frame = useCurrentFrame();

  const logoEntry = spring({
    frame,
    fps: FPS,
    config: { damping: 80, stiffness: 80 },
    durationInFrames: 30,
  });
  const logoScale = interpolate(logoEntry, [0, 1], [0.85, 1]);
  const tagOp = interpolate(frame, [30, 50], [0, 1], { extrapolateRight: "clamp" });
  const urlOp = interpolate(frame, [50, 70], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.bg,
        justifyContent: "center",
        alignItems: "center",
        fontFamily,
      }}
    >
      <AnimatedBg seed={8} intensity={0.25} />
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 50,
          zIndex: 1,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 40,
            opacity: logoEntry,
            transform: `scale(${logoScale})`,
          }}
        >
          <Img src={staticFile("mark.png")} style={{ width: 120, height: 120 }} />
          <span
            style={{
              fontSize: 80,
              fontWeight: 600,
              color: C.white,
              letterSpacing: "-0.02em",
            }}
          >
            CodePlane
          </span>
        </div>
        <p style={{ fontSize: 44, color: C.muted, textAlign: "center", opacity: tagOp }}>
          The operating layer for your coding agents.
        </p>
        <p
          style={{
            fontSize: 38,
            color: C.primary,
            fontWeight: 600,
            letterSpacing: "0.02em",
            opacity: urlOp,
          }}
        >
          github.com/dfinson/codeplane
        </p>
      </div>
    </AbsoluteFill>
  );
};
