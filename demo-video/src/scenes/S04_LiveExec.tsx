/**
 * S04 — Gate: Real Playwright-recorded approval click.
 *
 * Plays a WebM video of the actual approval flow captured via
 * Playwright with video recording enabled.
 */
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from "remotion";
import { SCENES } from "../constants";

export const S04_Gate: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.gate;

  // Fade in/out
  const opacity = interpolate(
    frame,
    [0, 10, dur - 10, dur],
    [0, 1, 1, 0.6],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#0d1117", opacity }}>
      <OffthreadVideo
        src={staticFile("captures/video-approval-click.webm")}
        startFrom={30}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
};
