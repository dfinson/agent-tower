/**
 * Terminal output processing utilities.
 *
 * Handles ANSI escape sequences and carriage-return overwrites so that
 * raw terminal output can be rendered in HTML (either via ansi-to-react
 * for colored output, or plain text for syntax-highlighted blocks).
 */

// All ANSI escape sequences (CSI, OSC, etc.)
// eslint-disable-next-line no-control-regex
const ANSI_RE = /\x1b(?:\[[0-9;?]*[A-Za-z]|\][^\x07\x1b]*(?:\x07|\x1b\\)|\([B0])/g;

// Non-SGR escape sequences (cursor movement, clear line, etc.)
// eslint-disable-next-line no-control-regex
const NON_SGR_RE = /\x1b(?:\[[0-9;?]*[A-HJ-Za-ln-z]|\][^\x07\x1b]*(?:\x07|\x1b\\)|\([B0])/g;

/**
 * Strip ALL ANSI escape sequences from text.
 * Use for content that will be syntax-highlighted or displayed as plain text.
 */
export function stripAnsi(text: string): string {
  return text.replace(ANSI_RE, "");
}

/**
 * Process raw terminal output for display with ansi-to-react.
 *
 * - Normalizes `\r\n` to `\n`
 * - Simulates carriage return (`\r` without `\n`) by keeping only the
 *   final overwrite of each line (progress bars, spinners)
 * - Strips non-SGR escape sequences (cursor movement, clear line/screen)
 * - Preserves SGR (color/style) sequences for ansi-to-react rendering
 */
export function processTerminalOutput(raw: string): string {
  // Strip non-SGR sequences (cursor movement, clear, OSC, etc.)
  let text = raw.replace(NON_SGR_RE, "");

  // Normalize \r\n → \n first
  text = text.replace(/\r\n/g, "\n");

  // Handle bare \r (carriage return without newline) — simulates overwriting
  // Split by newlines, process each line for \r overwrites
  const lines = text.split("\n");
  const processed = lines.map((line) => {
    if (!line.includes("\r")) return line;
    // Split on \r — the last segment is what's visible
    const segments = line.split("\r");
    const last = segments[segments.length - 1]!;
    // If the last segment is shorter than previous ones, it overwrites
    // only the beginning. For simplicity, just keep the last segment.
    return last;
  });

  return processed.join("\n");
}
