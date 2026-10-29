import { ArrowLeftIcon } from "lucide-react";
import { Link } from "react-router";

import { BoardHelp } from "@/components/help/BoardHelp";
import { HelpSection } from "@/components/help/HelpSection";
import { useScrollToHash } from "@/components/help/useScrollToHash";
import { Button } from "@/components/ui/button";
import {
  HELP_LINK_CLASSES,
  HELP_SECTIONS,
  RULES_PATH,
  type HelpSection as HelpSectionId,
} from "@/lib/help";

const TITLES = Object.fromEntries(
  HELP_SECTIONS.map(({ id, title }) => [id, title]),
) as Record<HelpSectionId, string>;

function HelpList({ items }: { items: string[] }) {
  return (
    <ul className="flex list-disc flex-col gap-1.5 pl-5">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function ScenariosHelp() {
  return (
    <>
      <p>
        Press New game on the game list and choose what you would like to do. There are
        three ways to play.
      </p>
      <HelpList
        items={[
          "Play against an agent. You play one side on this screen and the agent answers within its time budget.",
          "Play a friend with hints. You and a friend play on a real board at the table, and you enter each move here so the app can follow. Only you get hints.",
          "Watch two agents. Two agents play each other on this screen, and you start, pause and step through the match.",
        ]}
      />
      <p>
        On the screen the app is the board, and you play by tapping. At the table the app
        follows a real board. You make each move with the real pieces and then enter it
        here. When an agent plays at the table, it shows its move and waits until you have
        made it and pressed Done.
      </p>
      <p>
        After choosing, set the game up. Pick your colour (or let it be drawn), the agent
        and how strong it is, and whether you want hints. The name is optional. The app
        remembers your choices on this device, so the next similar game is New game and
        then Start game.
      </p>
      <p>
        Hints are suggestions from an agent for your own side. Press Hint on your turn to
        see one, and press it again to hide it. A hint is drawn on the board as a purple
        arrow and never played by itself. Tap the hinted piece and then its target to
        follow it.
      </p>
    </>
  );
}

function ControlsHelp() {
  return (
    <HelpList
      items={[
        "Tap a piece with a blue ring to select it, then tap a green hex to move it there. Tap the piece again, or an empty spot, to change your mind.",
        "To place a new piece, tap it in your hand tray below or above the board, then tap a green hex. The tray of the side to move has a honey edge.",
        "Pass appears only when no move is possible.",
        "Undo takes back the last move. Against an agent it takes back your last move and the agent's answer, so it is your turn again. In a match it pauses the match first.",
        "The move list and the replay buttons show earlier positions. Replayed positions are read only, and Go live returns to the game.",
        "Drag the board to pan it, pinch or use the mouse wheel to zoom, and press the fit button at the bottom right to see the whole hive again.",
        "Tap a stack of two or more pieces to see every piece in it from the top.",
      ]}
    />
  );
}

function GamesHelp() {
  return (
    <>
      <p>The game list says what each game waits for.</p>
      <HelpList
        items={[
          "Your turn. It is your move against an agent.",
          "A name to move, such as Sam to move. It is that person's move in a hints game.",
          "Agent's move to make. The agent has chosen its move, and it waits for you to make it on the table and press Done.",
          "An agent to move, such as nm3 to move. The agent plays when you open the game, or it is a match you are watching.",
          "White won, Black won or Draw. The game is finished, and you can still replay it.",
          "Abandoned. The game was stopped and can only be replayed.",
        ]}
      />
      <p>
        Under each name is the kind of game, vs agent, hints game or watching. Honey
        labels wait for you.
      </p>
    </>
  );
}

function LeavingHelp() {
  return (
    <HelpList
      items={[
        "The game is saved after every move, so you can close the page at any time.",
        "Closing the page while an agent thinks stops it without playing its move. The agent starts thinking again when you come back.",
        "An agent move waiting to be made at the table is kept until you press Done, also after a reload.",
        "A match comes back paused. Press Play to continue.",
        "Hints and the replayed position are not kept. Ask for a hint again when you return.",
      ]}
    />
  );
}

/**
 * How the app works: creating games, the colours and marks of the board, the controls,
 * the statuses and what is kept when you leave.
 */
export function HelpPage() {
  useScrollToHash();

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <div>
        <Button variant="ghost" asChild>
          <Link to="/">
            <ArrowLeftIcon />
            Games
          </Link>
        </Button>
      </div>
      <h1 className="font-heading text-2xl font-semibold">How the app works</h1>
      <p className="text-muted-foreground">
        The rules of the game itself are on the{" "}
        <Link to={RULES_PATH} className={HELP_LINK_CLASSES}>
          rules page
        </Link>
        .
      </p>
      <nav aria-label="Help sections">
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {HELP_SECTIONS.map(({ id, title }) => (
            <li key={id}>
              <a href={`#${id}`} className={HELP_LINK_CLASSES}>
                {title}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <HelpSection id="scenarios" title={TITLES.scenarios}>
        <ScenariosHelp />
      </HelpSection>
      <HelpSection id="board" title={TITLES.board}>
        <BoardHelp />
      </HelpSection>
      <HelpSection id="controls" title={TITLES.controls}>
        <ControlsHelp />
      </HelpSection>
      <HelpSection id="games" title={TITLES.games}>
        <GamesHelp />
      </HelpSection>
      <HelpSection id="leaving" title={TITLES.leaving}>
        <LeavingHelp />
      </HelpSection>
    </div>
  );
}
