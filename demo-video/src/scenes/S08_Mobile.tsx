/**
 * S08 — Mobile: parallax 3-D phone frames with floating rotation.
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
import { C, FPS, SCENES, PHONE } from "../constants";
import { AnimatedBg } from "../components/AnimatedBg";

const { fontFamily } = loadFont("normal", { weights: ["500"] });

interface PhoneProps {
  src: string;
  baseX: number;
  baseY: number;
  rotateY: number;
  delay: number;
  speed: number;
  frame: number;
}

const PhoneCard: React.FC<PhoneProps> = ({
  src, baseX, baseY, rotateY, delay, speed, frame,
}) => {
  const entry = spring({
    frame: Math.max(0, frame - delay),
    fps: FPS,
    config: { damping: 60, stiffness: 50 },
    durationInFrames: 40,
  });
  const entryY = interpolate(entry, [0, 1], [120, 0]);
  const floatY = Math.sin((frame + delay * 3) * 0.018 * speed) * 15;
  const floatX = Math.cos((frame + delay * 5) * 0.012 * speed) * 8;
  const rY = rotateY + Math.sin(frame * 0.01) * 2;
  const rX = Math.sin(frame * 0.008 + delay) * 3;

  return (
    <div
      style={{
        position: "absolute",
        left: baseX,
        top: baseY + entryY + floatY,
        transform: `translateX(${floatX}px) perspective(1200px) rotateY(${rY}deg) rotateX(${rX}deg)`,
        opacity: entry,
        transformStyle: "preserve-3d",
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
          boxShadow:
            "0 50px 100px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05), 0 0 60px rgba(59,130,246,0.08)",
        }}
      >
        <Img
          src={staticFile(src)}
          style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top" }}
        />
      </div>
    </div>
  );
};

export const S08_Mobile: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.mobile;

  const titleOp = interpolate(frame, [0, 15, 55, 70], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const titleSlide = interpolate(
    spring({ frame, fps: FPS, config: { damping: 80, stiffness: 100 }, durationInFrames: 20 }),
    [0, 1], [30, 0],
  );
  const fadeOut = interpolate(frame, [dur - 15, dur], [1, 0], { extrapolateLeft: "clamp" });

  const cx = (3840 - PHONE.width) / 2;
  const cy = (2160 - PHONE.height) / 2;

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, fontFamily, opacity: fadeOut }}>
      <AnimatedBg seed={7} intensity={0.4} />

      {/* Title */}
      <div style={{
        position: "absolute", top: 60, left: 0, right: 0,
        display: "flex", justifyContent: "center", zIndex: 2,
        opacity: titleOp, transform: `translateY(${titleSlide}px)`,
      }}>
        <h2 style={{
          fontSize: 72, fontWeight: 500, color: C.white,
          textShadow: "0 4px 40px rgba(0,0,0,0.9)", letterSpacing: "-0.02em",
        }}>
          Full visibility from anywhere.
        </h2>
      </div>

      <PhoneCard
        src="captures/dashboard-mobile.png"
        baseX={cx - 700}
        baseY={cy + 60}
        rotateY={14}
        delay={10}
        speed={1}
        frame={frame}
      />
      <PhoneCard
        src="captures/job-mobile.png"
        baseX={cx}
        baseY={cy - 40}
        rotateY={0}
        delay={0}
        speed={0.8}
        frame={frame}
      />
      <PhoneCard
        src="captures/job-approval.png"
        baseX={cx + 700}
        baseY={cy + 60}
        rotateY={-14}
        delay={20}
        speed={1.2}
        frame={frame}
      />
    </AbsoluteFill>
  );
};
