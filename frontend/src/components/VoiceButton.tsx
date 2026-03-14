/**
 * Voice recorder with WaveSurfer.js waveform visualization.
 *
 * Uses native browser APIs (getUserMedia + MediaRecorder) for recording.
 * WaveSurfer.js drives the live waveform from the browser audio stream.
 * Audio is recorded locally and uploaded as a single Blob after stop.
 */
import { useState, useRef, useCallback, useEffect } from "react";
import { ActionIcon, Paper, Text, Group, Loader } from "@mantine/core";
import { Mic, Square, Loader2 } from "lucide-react";
import WaveSurfer from "wavesurfer.js";
import RecordPlugin from "wavesurfer.js/dist/plugins/record.esm.js";
import { transcribeAudio } from "../api/client";
import { notifications } from "@mantine/notifications";

type RecordingState = "idle" | "recording" | "uploading" | "transcribing";

interface VoiceRecorderProps {
  onTranscript: (text: string) => void;
  maxSizeMb?: number;
}

export function VoiceRecorder({ onTranscript, maxSizeMb = 10 }: VoiceRecorderProps) {
  const [state, setState] = useState<RecordingState>("idle");
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const recordRef = useRef<ReturnType<typeof RecordPlugin.create> | null>(null);

  // Initialize WaveSurfer on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const record = RecordPlugin.create({
      renderRecordedAudio: false,
      scrollingWaveform: true,
      scrollingWaveformWindow: 4,
    });

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#5180c6",
      progressColor: "#7196cf",
      height: 32,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      plugins: [record],
    });

    wsRef.current = ws;
    recordRef.current = record;

    // Handle recording completion
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
          notifications.show({ color: "green", message: "Transcribed!" });
        }
      } catch {
        notifications.show({ color: "red", message: "Transcription failed" });
      } finally {
        setState("idle");
      }
    });

    return () => {
      record.destroy();
      ws.destroy();
    };
  }, [maxSizeMb, onTranscript]);

  const handleToggle = useCallback(async () => {
    const record = recordRef.current;
    if (!record) return;

    if (state === "recording") {
      record.stopRecording();
      setState("uploading");
      return;
    }

    try {
      await record.startRecording();
      setState("recording");
    } catch {
      notifications.show({ color: "red", message: "Microphone access denied" });
    }
  }, [state]);

  return (
    <Group gap="xs" align="center">
      {state === "recording" && (
        <Paper
          className="flex-1 overflow-hidden rounded-full"
          bg="dark.7"
          px="sm"
          py={4}
        >
          <div ref={containerRef} className="w-full" />
        </Paper>
      )}

      {state === "transcribing" && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="xs" c="dimmed">Transcribing…</Text>
        </Group>
      )}

      <ActionIcon
        variant={state === "recording" ? "filled" : "subtle"}
        color={state === "recording" ? "red" : "gray"}
        size="lg"
        radius="xl"
        onClick={handleToggle}
        disabled={state === "uploading" || state === "transcribing"}
        title={state === "recording" ? "Stop recording" : "Voice input"}
      >
        {state === "recording" ? (
          <Square size={14} />
        ) : state === "uploading" || state === "transcribing" ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Mic size={16} />
        )}
      </ActionIcon>

      {/* Hidden container for waveform when not recording */}
      {state !== "recording" && (
        <div ref={containerRef} className="hidden" />
      )}
    </Group>
  );
}

// Backward compatibility alias
export { VoiceRecorder as VoiceButton };
