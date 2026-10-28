import type { GameDetail, GamePosition } from "@/api/client";
import type { AgentTurnState } from "@/components/useAgentTurns";
import { boardBeforeMove, describeMoveOnBoard, toBoardView } from "@/lib/moves";
import { agentName, gameScenario, SIDE_TITLES } from "@/lib/players";

/**
 * What the game waits for now, which decides the actions of the turn prompt.
 *
 * - `replay`: an earlier position is shown; going live plays on.
 * - `pending`: an agent move to make on the table, confirmed with Done.
 * - `over` and `abandoned`: the game has ended.
 * - `watching`: an agent vs agent match, with the match controls.
 * - `thinking` and `failed`: an agent's turn in a game with a person.
 * - `turn`: a person's turn, with a hint for a side that has a hint agent.
 */
export type TurnPromptKind =
  | "replay"
  | "pending"
  | "over"
  | "abandoned"
  | "watching"
  | "thinking"
  | "failed"
  | "turn";

/** The prompt above the board: what the game waits for and one sentence on what to do. */
export interface TurnPrompt {
  kind: TurnPromptKind;
  text: string;
}

interface TurnPromptOptions {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
  /** The state of the agent turn at the latest position. */
  turnState: AgentTurnState["type"];
  /** The ply replayed, or `null` for the live position. */
  shownPly: number | null;
}

/** The result of a finished game, naming the person and the agent against an agent. */
function describeResult(game: GameDetail, position: GamePosition): string {
  const moves = `after ${position.ply_count} ${position.ply_count === 1 ? "move" : "moves"}`;

  if (position.result === null || position.result === "draw") {
    return `Draw ${moves}`;
  }

  const winner = game[position.result];

  if (gameScenario(game) === "agent") {
    return `${winner.type === "agent" ? agentName(winner.spec) : "You"} won ${moves}`;
  }

  return `${SIDE_TITLES[position.result]} won ${moves}`;
}

/** What a person whose turn it is does, by scenario and board location. */
function describePersonTurn(game: GameDetail, position: GamePosition): string {
  const againstAgent = gameScenario(game) === "agent";
  const turn = againstAgent
    ? "Your turn"
    : `${SIDE_TITLES[position.current_player]}'s turn`;

  if (position.must_pass) {
    return `${turn}: no move is possible, so pass`;
  }

  if (!againstAgent) {
    return `${turn}: make the move on the table and enter it`;
  }

  return game.board_location === "screen"
    ? `${turn}: tap a piece on the board or in your hand`
    : `${turn}: make your move on the table, then enter it here`;
}

/**
 * The turn prompt of a game: one sentence on what to do next for its scenario (D26) and
 * state, such as `Your turn: tap a piece on the board or in your hand` or `Make this
 * move on the table: ant moves next to the white queen`.
 *
 * A pending agent move comes from the stored position, so the prompt is the same after
 * a reload. It comes before the result, since the last move of a game can be pending.
 */
export function describeTurnPrompt({
  game,
  position,
  turnState,
  shownPly,
}: TurnPromptOptions): TurnPrompt {
  if (shownPly !== null) {
    return {
      kind: "replay",
      text: `Showing the position after move ${shownPly}: go live to play on`,
    };
  }

  if (position.pending_move) {
    const move = position.last_move?.move ?? null;
    const board = boardBeforeMove(toBoardView(position.board), move);

    return {
      kind: "pending",
      text: `Make this move on the table: ${describeMoveOnBoard(move, board)}`,
    };
  }

  if (position.result !== null) {
    return { kind: "over", text: describeResult(game, position) };
  }

  if (game.status !== "active") {
    return { kind: "abandoned", text: "This game was abandoned" };
  }

  if (game.white.type === "agent" && game.black.type === "agent") {
    return {
      kind: "watching",
      text: `Watching ${agentName(game.white.spec)} vs ${agentName(game.black.spec)}`,
    };
  }

  const player = game[position.current_player];

  if (player.type === "agent") {
    const name = agentName(player.spec);

    return turnState === "failed"
      ? { kind: "failed", text: `${name} could not move` }
      : { kind: "thinking", text: `${name} is thinking…` };
  }

  return { kind: "turn", text: describePersonTurn(game, position) };
}
