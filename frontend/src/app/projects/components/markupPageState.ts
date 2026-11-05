import type { MarkupPageState } from "@/types/tendering";

export function withPageState(
  pages: Record<string, MarkupPageState>,
  pageNumber: number,
  state: MarkupPageState,
): Record<string, MarkupPageState> {
  return { ...pages, [String(pageNumber)]: state };
}
