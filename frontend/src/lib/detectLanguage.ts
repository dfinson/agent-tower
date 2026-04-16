/** Map file extension → Prism language identifier for syntax highlighting. */

const EXT_MAP: Record<string, string> = {
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  rs: "rust",
  go: "go",
  rb: "ruby",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cs: "csharp",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  xml: "xml",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  less: "less",
  md: "markdown",
  sql: "sql",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  fish: "bash",
  ps1: "powershell",
  dockerfile: "docker",
  makefile: "makefile",
  graphql: "graphql",
  gql: "graphql",
  lua: "lua",
  r: "r",
  php: "php",
  pl: "perl",
  ex: "elixir",
  exs: "elixir",
  erl: "erlang",
  hs: "haskell",
  scala: "scala",
  tf: "hcl",
  ini: "ini",
  cfg: "ini",
  env: "bash",
};

const FILENAME_MAP: Record<string, string> = {
  dockerfile: "docker",
  makefile: "makefile",
  cmakelists: "cmake",
  gemfile: "ruby",
  rakefile: "ruby",
};

export function detectLanguage(filePath?: string): string | undefined {
  if (!filePath) return undefined;
  const parts = filePath.replace(/\\/g, "/").split("/");
  const fileName = (parts[parts.length - 1] ?? "").toLowerCase();

  // Check full filename first (Dockerfile, Makefile, etc.)
  const baseName = fileName.replace(/\.[^.]+$/, "");
  if (FILENAME_MAP[baseName]) return FILENAME_MAP[baseName];
  if (FILENAME_MAP[fileName]) return FILENAME_MAP[fileName];

  // Check extension
  const ext = fileName.includes(".") ? fileName.split(".").pop()! : "";
  return EXT_MAP[ext];
}
