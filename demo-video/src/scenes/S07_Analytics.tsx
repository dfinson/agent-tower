/**
 * S07 — Mobile: quick 3-beat phone montage.
 *
 * Three phone frames slide in sequentially, each showing a different beat:
 *   1. Dashboard (overview)
 *   2. Approval (approve from phone)
 *   3. Job detail (see the diff)
 *
 * This tells a story: "You're away from your desk. You still have full control."
 */
import { AbsoluteFill, Img, staticFile, useCurrentFrame, interpolate } from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { C, SCENES, PHONE } from "../constants";

const { fontFamily } = loadFont("normal", { weights: ["500"] });

const PhoneFrame: React.FC<{
  src: string;
  x: number;
  y: number;
  opacity: number;
  label?: string;
  labelOpacity?: number;
}> = ({ src, x, y, opacity, label, labelOpacity = 0 }) => (
  <div
    style={{
      position: "absolute",
      left: x,
      top: y,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 24,
      opacity,
    }}
  >
    <div
      style={{
        width: PHONE.width,
        height: PHONE.height,
        borderRadius: PHONE.radius,
        border: `${PHONE.bezel}px solid #2a2a30`,
        background: "#111",
        overflow: "hidden",
        boxShadow: "0 40px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05)",
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          objectPosition: "top",
        }}
      />
    </div>
    {label && (
      <span
        style={{
          fontSize: 28,
          color: C.muted,
          fontWeight: 500,
          opacity: labelOpacity,
          letterSpacing: "0.02em",
        }}
      >
        {label}
      </span>
    )}
  </div>
);

export const S07_Mobile: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.mobile;
  const centerY = (2160 - PHONE.height) / 2 - 20;

  // Title
  const titleOpacity = interpolate(frame, [0, 15, 75, 95], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Phone 1 — Dashboard (left) slides up
  const p1Y = interpolate(frame, [30, 65], [centerY + 100, centerY], { extrapolateRight: "clamp" });
  const p1Opacity = interpolate(frame, [30, 60], [0, 1], { extrapolateRight: "clamp" });
  const p1LabelOpacity = interpolate(frame, [65, 80], [0, 1], { extrapolateRight: "clamp" });

  // Phone 2 — Approval (center) slides up with delay
  const p2Y = interpolate(frame, [60, 95], [centerY + 100, centerY], { extrapolateRight: "clamp" });
  const p2Opacity = interpolate(frame, [60, 90], [0, 1], { extrapolateRight: "clamp" });
  const p2LabelOpacity = interpolate(frame, [95, 110], [0, 1], { extrapolateRight: "clamp" });

  // Phone 3 — Job detail (right) slides up with delay
  const p3Y = interpolate(frame, [90, 125], [centerY + 100, centerY], { extrapolateRight: "clamp" });
  const p3Opacity = interpolate(frame, [90, 120], [0, 1], { extrapolateRight: "clamp" });
  const p3LabelOpacity = interpolate(frame, [125, 140], [0, 1], { extrapolateRight: "clamp" });

  // Horizontal positions: 3 phones evenly spaced
  const totalWidth = PHONE.width * 3 + 200; // 200px gaps
  const startX = (3840 - totalWidth) / 2;

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily }}>
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
          pointerEvents: "none",
          opacity: titleOpacity,
        }}
      >
        <h2
          style={{
            fontSize: 72,
            fontWeight: 500,
            color: C.white,
            textShadow: "0 4px 40px rgba(0,0,0,0.9)",
            letterSpacing: "-0.02em",
          }}
        >
          From your phone. From anywhere.
        </h2>
      </div>

      {/* Three phones */}
      <PhoneFrame
        src="captures/dashboard-mobile.png"
        x={startX}
        y={p1Y}
        opacity={p1Opacity}
        label="Overview"
        labelOpacity={p1LabelOpacity}
      />
      <PhoneFrame
        src="captures/job-mobile.png"
        x={startX + PHONE.width + 100}
        y={p2Y}
        opacity={p2Opacity}
        label="Supervise"
        labelOpacity={p2LabelOpacity}
      />
      <PhoneFrame
        src="captures/dashboard-mobile.png"
        x={startX + (PHONE.width + 100) * 2}
        y={p3Y}
        opacity={p3Opacity}
        label="Approve"
        labelOpacity={p3LabelOpacity}
      />
    </AbsoluteFill>
  );
};
