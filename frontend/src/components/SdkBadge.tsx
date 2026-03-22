import { memo, type ReactElement } from "react";

// Inline SVG brand icons — kept minimal so they render cleanly at 10–12 px.

const GitHubCopilotIcon = ({ size }: { size: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
    style={{ display: "inline", flexShrink: 0 }}
  >
    {/* GitHub mark */}
    <path d="M12 0C5.374 0 0 5.373 0 12c0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.509 11.509 0 0 1 12 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576C20.566 21.797 24 17.3 24 12c0-6.627-5.373-12-12-12z" />
  </svg>
);

const ClaudeIcon = ({ size }: { size: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
    style={{ display: "inline", flexShrink: 0 }}
  >
    {/* Anthropic Claude mark — stylised A letterform */}
    <path d="M13.827 3.52h-3.654L2.317 21.558h3.467l1.822-3.578h8.797l1.821 3.578h3.468L13.827 3.52zm-4.958 11.84 3.424-7.775 3.423 7.775H8.869z" />
  </svg>
);

type SdkIconComponent = (props: { size: number }) => ReactElement;

const SDK_CONFIG: Record<
  string,
  { label: string; className: string; Icon: SdkIconComponent }
> = {
  copilot: {
    label: "GitHub Copilot",
    className:
      "bg-violet-500/15 text-violet-600 border-violet-500/30 dark:text-violet-400",
    Icon: GitHubCopilotIcon,
  },
  claude: {
    label: "Claude Code",
    className:
      "bg-orange-500/15 text-orange-600 border-orange-500/30 dark:text-orange-400",
    Icon: ClaudeIcon,
  },
};

const DEFAULT_CONFIG = {
  label: (sdk: string) => sdk,
  className: "bg-muted text-muted-foreground border-border",
};

interface SdkBadgeProps {
  sdk: string | undefined;
  /** Use "sm" for job cards, "md" (default) for the detail pane */
  size?: "sm" | "md";
}

export const SdkBadge = memo(function SdkBadge({ sdk, size = "md" }: SdkBadgeProps) {
  if (!sdk) return null;

  const cfg = SDK_CONFIG[sdk];
  const label = cfg?.label ?? DEFAULT_CONFIG.label(sdk);
  const className = cfg?.className ?? DEFAULT_CONFIG.className;
  const Icon = cfg?.Icon;

  const sizeClass =
    size === "sm" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]";
  const iconSize = size === "sm" ? 9 : 11;

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border font-semibold shrink-0 ${sizeClass} ${className}`}
    >
      {Icon && <Icon size={iconSize} />}
      {label}
    </span>
  );
});
