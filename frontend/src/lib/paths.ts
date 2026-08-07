/**
 * Cross-platform path helpers.
 *
 * Paths returned by the backend reflect the server's OS: POSIX paths use "/"
 * as the separator, but on Windows `pathlib.Path` renders absolute paths with
 * "\" (e.g. "C:\\Users\\dave\\myrepo"). Naively doing `path.split("/").pop()`
 * to get a display name is a no-op on those paths, since there's no "/" to
 * split on — the full path leaks into the UI instead of just the leaf name.
 */

/** Return the final path segment, splitting on both "/" and "\". */
export function pathBasename(path: string | null | undefined): string {
  if (!path) return "";
  const parts = path.split(/[/\\]/).filter(Boolean);
  return parts.length > 0 ? (parts[parts.length - 1] ?? path) : path;
}
