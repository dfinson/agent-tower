/**
 * Mantine dark theme configuration for Tower.
 *
 * Colors: slate/charcoal base, indigo/electric-blue accents.
 * Matches the developer-tool aesthetic described in the UI spec.
 */
import { createTheme, type MantineColorsTuple } from "@mantine/core";

// Electric blue/indigo accent palette
const accent: MantineColorsTuple = [
  "#eef3ff",
  "#dce4f5",
  "#b8c9e8",
  "#91aeda",
  "#7196cf",
  "#5d87c8",
  "#5180c6",
  "#416eaf",
  "#37629d",
  "#28548b",
];

export const theme = createTheme({
  primaryColor: "accent",
  colors: { accent },
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
  fontFamilyMonospace:
    '"JetBrains Mono", "Fira Code", "Cascadia Code", ui-monospace, monospace',
  defaultRadius: "md",
  cursorType: "pointer",
  components: {
    Button: { defaultProps: { variant: "default" } },
    Paper: { defaultProps: { withBorder: true } },
    Card: { defaultProps: { withBorder: true } },
  },
});
