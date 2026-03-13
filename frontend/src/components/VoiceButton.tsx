import { useState, useRef, useCallback } from "react";
import { transcribeAudio } from "../api/client";
import { Button } from "../ui/Button";
import { toast } from "sonner";

interface VoiceButtonProps {
  onTranscript: (text: string) => void;
  maxSizeMb?: number;
}

export function VoiceButton({ onTranscript, maxSizeMb = 10 }: VoiceButtonProps) {
  const [recording, setRecording] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);

  const toggle = useCallback(async () => {
    if (recording) {
      mediaRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: "audio/webm" });
        if (blob.size > maxSizeMb * 1024 * 1024) {
          toast.error(`Audio too large (max ${maxSizeMb} MB)`);
          return;
        }
        try {
          const text = await transcribeAudio(blob);
          if (text) onTranscript(text);
        } catch {
          toast.error("Transcription failed");
        }
      };
      recorder.start();
      mediaRef.current = recorder;
      setRecording(true);
    } catch {
      toast.error("Microphone access denied");
    }
  }, [recording, onTranscript, maxSizeMb]);

  return (
    <Button
      variant={recording ? "danger" : "ghost"}
      size="sm"
      onClick={toggle}
      title={recording ? "Stop recording" : "Voice input"}
    >
      {recording ? "⏹ Stop" : "🎤"}
    </Button>
  );
}
