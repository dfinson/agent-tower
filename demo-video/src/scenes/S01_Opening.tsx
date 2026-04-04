/**
 * S01 — Cold Open: real Playwright-recorded job creation flow.
 *
 * Plays a WebM video of the actual job creation UI captured via
 * Playwright with video recording enabled.
 */
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from "remotion";
import { SCENES } from "../constants";

export const S01_ColdOpen: React.FC = () => {
  const frame = useCurrentFrame();
  const dur = SCENES.coldOpen;

  // Fade in at start, fade out at end
  const opacity = interpolate(
    frame,
    [0, 8, dur - 10, dur],
    [0, 1, 1, 0.6],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#0d1117", opacity }}>
      <OffthreadVideo
        src={staticFile("captures/video-job-creation.webm")}
        startFrom={30}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
};
