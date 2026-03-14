/**
 * Voice recorder with WaveSurfer.js waveform visualization.
 *
 * Architecture:
 * - getUserMedia → MediaRecorder for recording (browser native)
 * - WaveSurfer.js RecordPlugin for live waveform display
 * - On stop: Blob uploaded to backend for transcription
 * - Result inserted into the parent's text field via onTranscript callback
 *
 * The waveform container is always mounted (but visually hidden when idle)
 * so WaveSurfer can initialize its canvas before recording starts.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import { ActionIcon, Loader, Tooltip } from "@mantine/core";
import { Mic, Square } from "lucide-react";
import WaveSurfer from "wavesurfer.js";
import RecordPlugin from "wavesurfer.js/dist/plugins/record.esm.js";
import { transcribeAudio } from "../api/client";
import { notifications } from "@mantine/notifications";

type RecordingState = "idle" | "recording" | "transcribing";

interface VoiceRecorderProps {
  onTranscript: (text: string) => void;
  maxSizeMb?: number;
}

export function VoiceRecorder({ onTranscript, maxSizeMb = 10 }: VoiceRecorderProps) {
  const [state, setState] = useState<RecordingState>("idle");
  const containerRef = useRef<HTMLDivElement>(null);
  const recordRef = useRef<ReturnType<typeof RecordPlugin.create> | null>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const initedRef = useRef(false);

  // Lazy-init WaveSurfer on first record attempt (container must be mounted)
  const ensureInit = useCallback(() => {
    if (initedRef.current || !containerRef.current) return;
    initedRef.current = true;

    const record = RecordPlugin.create({
      renderRecordedAudio: false,
      scrollingWaveform: true,
      scrollingWaveformWindow: 3,
    });

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#5180c6",
      progressColor: "#7196cf",
      height: 24,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      plugins: [record],
    });

    record.on("record-end", async (blob: Blob) => {
      if (blob.size > maxSizeMb * 1024 * 1024) {
        notifications.show({ color: "red", message: `Audio too large (max ${maxSizeMb} MB)` });
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const text = await transcribeAudio(blob);
        if (text) {
          onTranscript(text);
          notifications.show({ color: "green", message: "Transcribed" });
        }
      } catch {
        notifications.show({ color: "red", message: "Transcription failed" });
      } finally {
        setState("idle");
      }
    });

    wsRef.current = ws;
    recordRef.current = record;
  }, [maxSizeMb, onTranscript]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      recordRef.current?.destroy();
      wsRef.current?.destroy();
    };
  }, []);

  const handleToggle = useCallback(async () => {
    ensureInit();
    const record = recordRef.current;
    if (!record) return;

    if (state === "recording") {
      record.stopRecording();
      return;
    }

    try {
      await record.startRecording();
      setState("recording");
    } catch {
      notifications.show({ color: "red", message: "Microphone access denied" });
    }
  }, [state, ensureInit]);

  return (
    <div className="flex items-center gap-1">
      {/* Waveform container — always mounted, visible only during recording */}
      <div
        ref={containerRef}
        className={`overflow-hidden rounded-full transition-all ${
          state === "recording"
            ? "w-24 h-6 bg-[var(--mantine-color-dark-7)] px-1"
            : "w-0 h-0"
        }`}
      />

      {state === "transcribing" ? (
        <Loader size={16} />
      ) : (
        <Tooltip label={state === "recording" ? "Stop" : "Voice input"} withArrow>
          <ActionIcon
            variant={state === "recording" ? "filled" : "subtle"}
            color={state === "recording" ? "red" : "gray"}
            size="sm"
            radius="xl"
            onClick={handleToggle}
          >
            {state === "recording" ? <Square size={12} /> : <Mic size={14} />}
          </ActionIcon>
        </Tooltip>
      )}
    </div>
  );
}
