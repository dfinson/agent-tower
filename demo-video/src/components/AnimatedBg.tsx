/**
 * Animated gradient orbs — drifting background for visual depth.
 */
import { useCurrentFrame, interpolate } from "remotion";

const ORBS = [
  { sx: 20, ex: 38, sy: 25, ey: 48, color: "hsla(217,91%,60%,0.35)", size: 900 },
  { sx: 65, ex: 50, sy: 65, ey: 32, color: "hsla(270,60%,50%,0.28)", size: 700 },
  { sx: 45, ex: 62, sy: 80, ey: 52, color: "hsla(200,80%,45%,0.22)", size: 800 },
];

export const AnimatedBg: React.FC<{ seed?: number; intensity?: number }> = ({
  seed = 0,
  intensity = 0.5,
}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", opacity: intensity }}>
      {ORBS.map((o, i) => {
        const drift = seed * 5 * (i % 2 === 0 ? 1 : -1);
        const x = interpolate(frame, [0, 600], [o.sx + drift, o.ex + drift], {
          extrapolateRight: "clamp",
        });
        const y = interpolate(frame, [0, 600], [o.sy, o.ey], {
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${x}%`,
              top: `${y}%`,
              width: o.size,
              height: o.size,
              borderRadius: "50%",
              background: `radial-gradient(circle, ${o.color} 0%, transparent 70%)`,
              filter: "blur(120px)",
              transform: "translate(-50%,-50%)",
            }}
          />
        );
      })}
    </div>
  );
};
