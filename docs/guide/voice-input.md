# Voice Input

CodePlane supports voice input for prompts and operator messages, using local Whisper transcription for privacy.

## How It Works

1. Click the **microphone button** (🎤) next to any text input
2. Speak your prompt or instruction
3. Audio is recorded in the browser using the Web Audio API
4. The recording is sent to the backend for transcription
5. **faster-whisper** transcribes locally — no data leaves your machine
6. The transcription appears in the text field for review and editing

## Where You Can Use Voice

- **Job creation prompt** — Dictate the task description
- **Operator messages** — Speak instructions to the running agent

## Privacy

Voice transcription runs entirely on your local machine using [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No audio data is sent to any external API. The Whisper model is downloaded once and cached locally.

## Requirements

The backend must have `faster-whisper` installed (included in the default dependencies). The first transcription may take a moment while the model loads.
