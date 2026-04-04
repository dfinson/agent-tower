import { useRef } from "react";
import { useStore, selectJobSteps, selectActiveStep } from "../store";
import type { JobSummary } from "../store";
import { useIsMobile } from "../hooks/useIsMobile";
import { StepContainer } from "./StepContainer";
import { StepSearchBar } from "./StepSearchBar";
import { ResumeBanner } from "./ResumeBanner";

interface StepListViewProps {
  job: JobSummary;
}

export function StepListView({ job }: StepListViewProps) {
  const jobId = job.id;
  const steps = useStore(selectJobSteps(jobId));
  const activeStep = useStore(selectActiveStep(jobId));
  const isMobile = useIsMobile();
  const activeStepRef = useRef<HTMLDivElement | null>(null);
  const listTopRef = useRef<HTMLDivElement | null>(null);
  const isRunning = job.state === "running" || job.state === "agent_running";

  const scrollToActiveStep = () => {
    activeStepRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const scrollToTop = () => {
    listTopRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="relative flex flex-col">
      <div ref={listTopRef} />

      <StepSearchBar jobId={jobId} />

      <ResumeBanner jobId={jobId} onJumpToFirst={scrollToTop} />

      {steps.length === 0 && (
        <div className="py-8 text-center text-sm text-muted-foreground">
          {isRunning ? "Waiting for first step…" : "No steps recorded."}
        </div>
      )}

      <div className="flex flex-col">
        {steps.map((step) => {
          const isActive = step.stepId === activeStep?.stepId;
          return (
            <div
              key={step.stepId}
              data-step-id={step.stepId}
              ref={isActive ? activeStepRef : undefined}
            >
              <StepContainer step={step} isActive={isActive} />
            </div>
          );
        })}
      </div>

      {/* Jump to current step */}
      {isRunning && activeStep && (
        isMobile ? (
          <button
            onClick={scrollToActiveStep}
            className="fixed bottom-20 left-1/2 -translate-x-1/2 z-40 px-4 py-2 rounded-full
                       bg-primary text-primary-foreground text-sm font-medium shadow-lg min-h-[44px]"
          >
            Jump to current step ↓
          </button>
        ) : (
          <div className="sticky bottom-0 flex gap-2 p-2 bg-card/95 backdrop-blur border-t">
            <button
              onClick={scrollToActiveStep}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Jump to current step
            </button>
          </div>
        )
      )}
    </div>
  );
}
