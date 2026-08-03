export interface RepositoryPathDisplay {
  display: string;
  raw: string;
}

interface NormalizedPath {
  value: string;
  absolute: boolean;
  windows: boolean;
  escaped: boolean;
}

function normalizePath(raw: string): NormalizedPath {
  const slashed = raw.replace(/\\/g, "/");
  const windowsDrive = /^[A-Za-z]:\//.test(slashed);
  const windowsUnc = slashed.startsWith("//");
  const windows = windowsDrive || windowsUnc;
  const absolute = windows || slashed.startsWith("/");
  const prefix = windowsDrive ? slashed.slice(0, 2).toUpperCase() : windowsUnc ? "//" : absolute ? "/" : "";
  const remainder = windowsDrive ? slashed.slice(2) : windowsUnc ? slashed.slice(2) : absolute ? slashed.slice(1) : slashed;
  const segments: string[] = [];
  let escaped = false;

  for (const segment of remainder.split("/")) {
    if (!segment || segment === ".") continue;
    if (segment === "..") {
      if (segments.length === 0) {
        escaped = true;
      } else {
        segments.pop();
      }
      continue;
    }
    segments.push(segment);
  }

  const joined = segments.join("/");
  const value = windowsDrive ? `${prefix}/${joined}` : windowsUnc ? `${prefix}${joined}` : absolute ? `/${joined}` : joined;
  return { value: value.replace(/\/$/, ""), absolute, windows, escaped };
}

export function repositoryRelativePath(rawPath: string, worktreeRoot?: string | null): string | null {
  if (!rawPath) return null;
  const candidate = normalizePath(rawPath);
  if (candidate.escaped) return null;
  if (!candidate.absolute) return candidate.value || ".";
  if (!worktreeRoot) return null;

  const root = normalizePath(worktreeRoot);
  if (!root.absolute || root.escaped || root.windows !== candidate.windows) return null;
  const candidateForCompare = candidate.windows ? candidate.value.toLowerCase() : candidate.value;
  const rootForCompare = root.windows ? root.value.toLowerCase() : root.value;
  if (candidateForCompare === rootForCompare) return ".";
  const boundary = rootForCompare === "/" ? "/" : `${rootForCompare}/`;
  if (!candidateForCompare.startsWith(boundary)) return null;
  return candidate.value.slice(boundary.length) || ".";
}

export function repositoryPathDisplay(
  rawPath: string,
  worktreeRoot?: string | null,
): RepositoryPathDisplay | null {
  const relative = repositoryRelativePath(rawPath, worktreeRoot);
  return relative == null ? null : { display: relative, raw: rawPath };
}

export function trimWorktreeRoot(text: string, worktreeRoot?: string | null): string {
  if (!text || !worktreeRoot) return text;
  const root = normalizePath(worktreeRoot);
  if (!root.absolute || root.escaped) return text;
  const variants = root.windows
    ? [root.value, root.value.replace(/\//g, "\\")]
    : [root.value];
  let result = text;
  for (const variant of variants) {
    const escaped = variant.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = result.replace(
      new RegExp(`(^|[\\s"'=(])${escaped}(?=[\\\\/])`, root.windows ? "gi" : "g"),
      "$1.",
    );
  }
  return result;
}
