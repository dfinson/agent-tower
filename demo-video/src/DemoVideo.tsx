/**
 * DemoVideo — main composition: "one job, full lifecycle" narrative.
 *
 * 8 scenes, ~78 seconds. Follows a single job from prompt to merge,
 * with each scene advancing the story rather than listing features.
 *
 * Transition strategy:
 *   - Fades between conceptual shifts (open→dashboard, analytics→mobile, mobile→cta)
 *   - Slides between product screens that follow the workflow
 */
import {
  TransitionSeries,
  linearTiming,
} from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";
import { SCENES, TRANSITION_FRAMES } from "./constants";
import { S01_ColdOpen } from "./scenes/S01_Opening";
import { S02_ScaleReveal } from "./scenes/S02_Problem";
import { S03_Supervise } from "./scenes/S03_Dashboard";
import { S04_Gate } from "./scenes/S04_LiveExec";
import { S05_Review } from "./scenes/S05_PlanDiff";
import { S06_CostScale } from "./scenes/S06_Approval";
import { S07_Mobile } from "./scenes/S07_Analytics";
import { S08_CTA } from "./scenes/S08_Mobile";

const T = TRANSITION_FRAMES;
const timing = linearTiming({ durationInFrames: T });

export const DemoVideo: React.FC = () => {
  return (
    <TransitionSeries>
      {/* S01: Cold open — typing prompt, launching job */}
      <TransitionSeries.Sequence durationInFrames={SCENES.coldOpen}>
        <S01_ColdOpen />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={timing} />

      {/* S02: Scale reveal — zoom out to full Kanban dashboard */}
      <TransitionSeries.Sequence durationInFrames={SCENES.scaleReveal}>
        <S02_ScaleReveal />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={timing}
      />

      {/* S03: Supervise — live transcript streaming */}
      <TransitionSeries.Sequence durationInFrames={SCENES.supervise}>
        <S03_Supervise />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-left" })}
        timing={timing}
      />

      {/* S04: Gate — approval with cursor click */}
      <TransitionSeries.Sequence durationInFrames={SCENES.gate}>
        <S04_Gate />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition
        presentation={slide({ direction: "from-right" })}
        timing={timing}
      />

      {/* S05: Review — diff viewer with pan */}
      <TransitionSeries.Sequence durationInFrames={SCENES.review}>
        <S05_Review />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={timing} />

      {/* S06: Cost + Scale — analytics then dashboard loop */}
      <TransitionSeries.Sequence durationInFrames={SCENES.costScale}>
        <S06_CostScale />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={timing} />

      {/* S07: Mobile — 3-phone montage */}
      <TransitionSeries.Sequence durationInFrames={SCENES.mobile}>
        <S07_Mobile />
      </TransitionSeries.Sequence>
      <TransitionSeries.Transition presentation={fade()} timing={timing} />

      {/* S08: CTA — logo + install + GitHub */}
      <TransitionSeries.Sequence durationInFrames={SCENES.cta}>
        <S08_CTA />
      </TransitionSeries.Sequence>
    </TransitionSeries>
  );
};
