/**
 * Narrative-driven scene titles.
 * Each title is tied to a story beat, not a feature bullet.
 */

import { SCENES, TRANSITION_FRAMES } from "./constants";

interface Title {
  text: string;
  /** Sub-text shown below the main title */
  sub?: string;
  startFrame: number;
  endFrame: number;
  /** Position: 'center' (default), 'bottom', 'top' */
  position?: "center" | "bottom" | "top";
}

// Compute the absolute start frame for scene at `index`
function sceneStart(index: number): number {
  const keys = Object.keys(SCENES) as (keyof typeof SCENES)[];
  let frame = 0;
  for (let i = 0; i < index; i++) {
    frame += SCENES[keys[i]] - TRANSITION_FRAMES;
  }
  return frame;
}

const S = SCENES;

export const titles: Title[] = [
  // S01 — Cold open: no title, the typing IS the content

  // S02 — Scale reveal
  {
    text: "One view. Every agent. Every repo.",
    startFrame: sceneStart(1) + 15,
    endFrame: sceneStart(1) + 100,
    position: "top",
  },

  // S03 — Supervise
  {
    text: "Watch it think. Watch it build.",
    startFrame: sceneStart(2) + 10,
    endFrame: sceneStart(2) + 80,
  },

  // S04 — Gate
  {
    text: "You stay in control.",
    startFrame: sceneStart(3) + 10,
    endFrame: sceneStart(3) + 70,
  },

  // S05 — Review
  {
    text: "Review every change before it lands.",
    startFrame: sceneStart(4) + 10,
    endFrame: sceneStart(4) + 80,
  },

  // S06 — Cost + Scale
  {
    text: "Know what it costs.",
    startFrame: sceneStart(5) + 10,
    endFrame: sceneStart(5) + 70,
  },

  // S07 — Mobile
  {
    text: "From your phone. From anywhere.",
    startFrame: sceneStart(6) + 10,
    endFrame: sceneStart(6) + 80,
  },

  // S08 — CTA: handled inline by the closing scene
];

export function getTitleAtFrame(frame: number): Title | null {
  return titles.find((t) => frame >= t.startFrame && frame < t.endFrame) ?? null;
}
