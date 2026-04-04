/**
 * Timing, colors, and layout constants for the CodePlane demo video.
 *
 * Composition: 3840×2160 at 30 fps.
 * Target duration: ~78 seconds — "one job, full lifecycle" narrative.
 *
 * Narrative arc:
 *   1. Cold open — prompt typed, job launched        (3s)
 *   2. Scale reveal — pull back to full Kanban board  (8s)
 *   3. Supervise — live transcript streaming           (13s)
 *   4. Gate — approval card appears, gets approved     (10s)
 *   5. Review — diff viewer, scroll through changes    (13s)
 *   6. Cost + scale — analytics, then dashboard loop   (10s)
 *   7. Mobile — quick 3-beat phone montage             (10s)
 *   8. CTA — logo + install command + GitHub URL       (8s)
 */

export const FPS = 30;
export const WIDTH = 3840;
export const HEIGHT = 2160;
export const TRANSITION_FRAMES = 10;

// Scene durations in frames
export const SCENES = {
  coldOpen: 210,       //  7.0s — real video: prompt typed + job created
  scaleReveal: 240,    //  8.0s — zoom out to full Kanban dashboard
  supervise: 390,      // 13.0s — live transcript with simulated streaming
  gate: 150,           //  5.0s — real video: approval click
  review: 390,         // 13.0s — diff viewer with pan through changes
  costScale: 300,      // 10.0s — analytics + dashboard completion loop
  mobile: 300,         // 10.0s — phone montage: board → approve → diff
  cta: 240,            //  8.0s — logo + pip install + GitHub URL
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
  green: "#22c55e",
  // Brand
  claude: "#D97757",
  copilot: "#8534F3",
} as const;

// Phone frame dimensions for mobile scene (iPhone 14 Pro proportions)
export const PHONE = {
  width: 440,
  height: 900,
  radius: 48,
  bezel: 8,
} as const;

// Shared visual constants
export const SCREENSHOT_STYLE = {
  width: "94%" as const,
  borderRadius: 20,
  boxShadow: "0 30px 100px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.06)",
};
