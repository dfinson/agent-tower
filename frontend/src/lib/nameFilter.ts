/**
 * Generic, reusable name-filter predicate for card-rendering layers.
 * Used by the Projects Overview grid and sidebar Project list (Story 2.5),
 * and intended to be reused for Task Recipe/TaskLink cards once Epic 4
 * introduces them, rather than re-implemented per feature.
 */
export function matchesNameFilter(name: string, query: string): boolean {
  const trimmedQuery = query.trim().toLowerCase();
  if (trimmedQuery === "") return true;
  return name.toLowerCase().includes(trimmedQuery);
}
