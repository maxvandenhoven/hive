/*
 * What the game page explains for its scenario and state, namely the short answer of
 * its help button and the board tips above the board.
 */
import type { GameDetail, GamePosition } from "@/api/client";
import { helpPath, rulesPath } from "@/lib/help";
import { gameScenario, type GameScenario } from "@/lib/players";
import type { TurnPromptKind } from "@/lib/turnPrompt";

/** The short answer of the game page's help button, with the section that says more. */
export interface GameHelp {
  title: string;
  text: string;
  to: string;
}

interface GameHelpOptions {
  game: GameDetail;
  /** The latest position. */
  position: GamePosition;
  /** What the turn prompt waits for. */
  kind: TurnPromptKind;
}

/** How a person enters a move, by scenario. */
const PERSON_TURN_HELP: Record<GameScenario, string> = {
  agent:
    "Tap a piece with a blue ring to see where it can go, then tap a green hex. To place a new piece, tap it in your hand first.",
  hints:
    "Make the move on the real board, then enter the same move here by tapping the piece and its green target. Only you can ask for a hint.",
  watch: "Two agents play each other here.",
};

/** The help for the current scenario and turn of a game. */
export function describeGameHelp({ game, position, kind }: GameHelpOptions): GameHelp {
  const scenario = gameScenario(game);

  switch (kind) {
    case "replay":
      return {
        title: "Replaying the game",
        text: "This is an earlier position, so the board is read only. Press Go live to return to the game.",
        to: helpPath("controls"),
      };
    case "pending":
      return {
        title: "Making the agent's move",
        text: "The purple arrow shows the move the agent chose. Make it with the real pieces, then press Done. The move is kept until then, also when you leave.",
        to: helpPath("leaving"),
      };
    case "over":
      return {
        title: "The game is over",
        text: "A queen surrounded on all six sides loses, and two at once is a draw. Undo takes the last move back, or start a new game.",
        to: rulesPath("end"),
      };
    case "abandoned":
      return {
        title: "An abandoned game",
        text: "This game was stopped. You can still replay its moves.",
        to: helpPath("games"),
      };
    case "watching":
      return {
        title: "Watching a match",
        text: "Press Play to let the agents play, Pause to stop and Step to play one move at a time. A match comes back paused when you leave.",
        to: helpPath("controls"),
      };
    case "thinking":
      return {
        title: "The agent is thinking",
        text: "The agent searches within its time budget, and its best move so far is drawn in purple. Leaving the page stops it, and it starts again when you return.",
        to: helpPath("leaving"),
      };
    case "failed":
      return {
        title: "The agent could not move",
        text: "Something went wrong while the agent was thinking. Press Try again to let it think once more.",
        to: helpPath("leaving"),
      };
    case "turn":
      if (position.must_pass) {
        return {
          title: "No move is possible",
          text: "No piece can be placed or moved, so the only move is to pass.",
          to: rulesPath("passing"),
        };
      }

      return {
        title: "Your move",
        text: PERSON_TURN_HELP[scenario],
        to: helpPath("controls"),
      };
  }
}

/** A tip shown above the board, dismissed by its id. */
export interface BoardTip {
  id: string;
  text: string;
  /** A rule or help section that explains the tip. */
  link?: { to: string; label: string };
}

interface BoardTipsOptions extends GameHelpOptions {
  /** Whether the side to move can ask for a hint. */
  hintAvailable: boolean;
}

/** Whether only the queen may be placed, since the fourth turn came without it. */
function queenRequired(position: GamePosition): boolean {
  const hand = position.hands[position.current_player] ?? {};
  const others = Object.entries(hand).filter(
    ([piece, count]) => piece !== "queen" && count > 0,
  );

  return (
    position.placeable_piece_types.length === 1 &&
    position.placeable_piece_types[0] === "queen" &&
    others.length > 0
  );
}

/** The tips for the current scenario and state, in the order they are shown. */
export function boardTips({
  game,
  position,
  kind,
  hintAvailable,
}: BoardTipsOptions): BoardTip[] {
  const scenario = gameScenario(game);

  if (kind === "pending") {
    return [
      {
        id: "make-agent-move",
        text: "Make the agent's move on the table, then press Done.",
      },
    ];
  }

  if (kind === "watching") {
    return [
      {
        id: "watch-match",
        text: "Press Play to start the match, or Step to play one move at a time.",
      },
    ];
  }

  if (kind !== "turn") {
    return [];
  }

  if (position.must_pass) {
    return [
      {
        id: "must-pass",
        text: "No move is possible, so press Pass.",
        link: { to: rulesPath("passing"), label: "Passing" },
      },
    ];
  }

  const tips: BoardTip[] = [];

  if (scenario === "hints") {
    tips.push({
      id: "enter-table-move",
      text: "Make the move on the table, then tap the same piece and target here.",
    });
  }

  if (queenRequired(position)) {
    tips.push({
      id: "queen-by-fourth-turn",
      text: "The queen must be placed by the fourth turn, so only the queen can be placed now.",
      link: { to: rulesPath("placement"), label: "Placing pieces" },
    });
  } else if (position.ply_count >= 2 && position.placeable_piece_types.length > 0) {
    tips.push({
      id: "place-own-colour",
      text: "Tap a piece in your hand to place it. New pieces only touch your own colour.",
      link: { to: rulesPath("placement"), label: "Placing pieces" },
    });
  }

  if (position.movable_pieces.length > 0) {
    tips.push({
      id: "tap-movable",
      text: "Tap a piece with a blue ring to see where it can go.",
    });
  }

  if (hintAvailable) {
    tips.push({ id: "ask-hint", text: "Press Hint for a suggestion." });
  }

  return tips;
}
