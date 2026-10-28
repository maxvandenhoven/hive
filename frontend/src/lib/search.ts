/** The search progress an agent reported last, such as `depth`, `score` and `nps`. */
export type ThinkInfo = Record<string, unknown>;

/** The score of a won position in the search agents, reduced by one per ply to the win. */
export const SEARCH_WIN_SCORE = 1_000_000;

/** Scores this close to `SEARCH_WIN_SCORE` are forced wins or losses. */
const FORCED_RESULT_MARGIN = 1_000;

/** The common fields of a search progress report, `null` where an agent left one out. */
export interface SearchSummary {
  depth: number | null;
  score: number | null;
  nodes: number | null;
  nps: number | null;
}

function numberField(info: ThinkInfo, field: string): number | null {
  const value = info[field];

  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Read the common fields of a progress report, which agents fill as they like. */
export function summarizeSearch(info: ThinkInfo | null): SearchSummary {
  return {
    depth: info === null ? null : numberField(info, "depth"),
    score: info === null ? null : numberField(info, "score"),
    nodes: info === null ? null : numberField(info, "nodes"),
    nps: info === null ? null : numberField(info, "nps"),
  };
}

/**
 * A score from the view of the side to move, such as `+1.5`, or `Win in 3 plies` for a
 * forced result.
 */
export function formatScore(score: number): string {
  const plies = SEARCH_WIN_SCORE - Math.abs(score);

  if (plies <= FORCED_RESULT_MARGIN) {
    const unit = Math.round(plies) === 1 ? "ply" : "plies";

    return `${score > 0 ? "Win" : "Loss"} in ${Math.round(plies)} ${unit}`;
  }

  return `${score > 0 ? "+" : ""}${score.toFixed(1)}`;
}

const countFormat = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** A count such as nodes per second, shortened to `12.3K` or `1.2M`. */
export function formatCount(count: number): string {
  return countFormat.format(count);
}
