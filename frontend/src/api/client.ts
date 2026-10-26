import createClient from "openapi-fetch";

import type { components, paths } from "@/api/schema";

type Schemas = components["schemas"];

export type AgentPlayer = Schemas["AgentPlayer"];
export type AgentRegistration = Schemas["AgentRegistration"];
export type AgentSpec = Schemas["AgentSpec"];
export type BoardCell = Schemas["BoardCell"];
export type Coordinate = Schemas["Coordinate"];
export type GameCreate = Schemas["GameCreate"];
export type GameDetail = Schemas["GameDetail"];
export type GamePage = Schemas["GamePage"];
export type GamePosition = Schemas["GamePosition"];
export type GameResult = Schemas["GameResult"];
export type GameStatus = Schemas["GameStatus"];
export type GameSummary = Schemas["GameSummary"];
export type GameUpdate = Schemas["GameUpdate"];
export type HumanPlayer = Schemas["HumanPlayer"];
export type MovablePiece = Schemas["MovablePiece"];
export type Move = Schemas["Move"];
export type MoveCreate = Schemas["MoveCreate"];
export type MoveRead = Schemas["MoveRead"];
export type MoveSource = Schemas["MoveSource"];
export type Piece = Schemas["Piece"];
export type PieceTargets = Schemas["PieceTargets"];
export type PieceType = Piece["piece"];
export type PlayerConfig = Schemas["PlayerConfig"];
export type Rules = Schemas["Rules"];

/** A failed API request, with the error code and message the API sent. */
export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: Schemas["ApiErrorCode"] | null;

  constructor(status: number, body: unknown) {
    super(describeErrorBody(status, body));
    this.name = "ApiRequestError";
    this.status = status;
    this.code = isErrorResponse(body) ? body.code : null;
  }
}

function isErrorResponse(body: unknown): body is Schemas["ErrorResponse"] {
  return typeof body === "object" && body !== null && "code" in body && "detail" in body;
}

/** Turn an error body (`ErrorResponse` or a validation error) into one message. */
function describeErrorBody(status: number, body: unknown): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const { detail } = body;

    if (typeof detail === "string") {
      return detail;
    }

    if (Array.isArray(detail)) {
      const errors = detail as Schemas["ValidationError"][];

      return errors.map((error) => error.msg).join("; ");
    }
  }

  return `The request failed with status ${status}.`;
}

/** The typed client of the API, on the origin that serves the app. */
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Look up `fetch` per request rather than once, so tests can replace it.
  fetch: (request) => globalThis.fetch(request),
});

/** Return the data of a response, or throw an `ApiRequestError` for an error. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok) {
    throw new ApiRequestError(result.response.status, result.error);
  }

  return result.data as T;
}

/** The URL that downloads a game as a JSON `GameRecord`. */
export function gameExportUrl(gameId: string): string {
  return `/api/games/${encodeURIComponent(gameId)}/export`;
}
