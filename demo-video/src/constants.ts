/**
 * Timing, colors, and layout constants for the CodePlane demo video.
 *
 * Composition: 3840×2160 at 30 fps.
 * Target duration: ~75 seconds.
 */

export const FPS = 30;
export const WIDTH = 3840;
export const HEIGHT = 2160;
export const TRANSITION_FRAMES = 10;

// Scene durations in frames
export const SCENES = {
  opening: 210,        //  7.0s — real video: job creation
  problem: 90,         //  3.0s — "every agent is a black box"
  dashboard: 240,      //  8.0s — zoom out to full Kanban dashboard
  liveExecution: 390,  // 13.0s — live transcript streaming
  planDiff: 390,       // 13.0s — diff viewer with pan
  approval: 150,       //  5.0s — real video: approval click
  analytics: 300,      // 10.0s — analytics + dashboard loop
  mobile: 300,         // 10.0s — phone montage
  closing: 240,        //  8.0s — logo + pip install + GitHub URL
} as const;

export const TOTAL_FRAMES = Object.values(SCENES).reduce((a, b) => a + b, 0)
  - TRANSITION_FRAMES * (Object.keys(SCENES).length - 1);

// Colors — extracted from frontend/src/index.css
export const C = {
  bg: "hsl(220 20% 7%)",
  card: "hsl(215 22% 11%)",
  border: "hsl(215 12% 21%)",
  fg: "hsl(213 27% 90%)",
  muted: "hsl(215 12% 57%)",
  primary: "hsl(217 91% 60%)",
  white: "#ffffff",
  // Brand
  claude: "#D97757",
  copilot: "#8534F3",
} as const;

// Phone frame dimensions for mobile scene (iPhone 14 Pro proportions)
export const PHONE = {
  width: 560,
  height: 1140,
  radius: 56,
  bezel: 10,
} as const;
