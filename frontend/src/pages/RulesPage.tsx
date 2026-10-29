import { ArrowLeftIcon } from "lucide-react";
import { Link } from "react-router";

import type { PieceType } from "@/api/client";
import { PieceIcon } from "@/components/board/PieceTile";
import { HelpSection } from "@/components/help/HelpSection";
import { RulesDiagram } from "@/components/help/RulesDiagram";
import { SearchableSections } from "@/components/help/SearchableSections";
import { Button } from "@/components/ui/button";
import { RULES_SECTIONS, type RulesSection } from "@/lib/help";

const TITLES = Object.fromEntries(
  RULES_SECTIONS.map(({ id, title }) => [id, title]),
) as Record<RulesSection, string>;

const PIECES: readonly {
  piece: PieceType;
  name: string;
  count: string;
  moves: string;
}[] = [
  { piece: "queen", name: "Queen bee", count: "1", moves: "slides one hex per turn." },
  {
    piece: "beetle",
    name: "Beetle",
    count: "2",
    moves: "moves one hex per turn and may climb on top of other pieces.",
  },
  {
    piece: "grasshopper",
    name: "Grasshopper",
    count: "3",
    moves: "jumps in a straight line over a row of pieces.",
  },
  {
    piece: "spider",
    name: "Spider",
    count: "2",
    moves: "slides exactly three hexes around the hive.",
  },
  {
    piece: "ant",
    name: "Soldier ant",
    count: "3",
    moves: "slides any number of hexes around the hive.",
  },
];

function PieceList() {
  return (
    <ul className="flex flex-col gap-3">
      {PIECES.map(({ piece, name, count, moves }) => (
        <li key={piece} className="flex items-center gap-3">
          <PieceIcon piece={{ piece, owner: "white" }} className="size-9" />
          <span>
            <span className="font-medium">{name}</span>
            <span className="text-muted-foreground"> ({count} per player)</span> {moves}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Diagrams({ ids }: { ids: string[] }) {
  return (
    <div className="grid gap-6 sm:grid-cols-2">
      {ids.map((id) => (
        <RulesDiagram key={id} id={id} />
      ))}
    </div>
  );
}

/**
 * The rules of the base game, one section per rule, each with diagrams whose allowed
 * and forbidden targets are checked against the engine.
 */
export function RulesPage() {
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
      <h1 className="font-heading text-2xl font-semibold">Game rules</h1>
      <p className="text-muted-foreground">
        In the diagrams a blue ring highlights the piece the text next to it is about.
        Green hexes show where that piece may go and crossed out red hexes show where it
        may not. Every diagram is checked against the engine of this app.
      </p>
      <SearchableSections label="Search the rules">
        <HelpSection id="pieces" title={TITLES.pieces}>
          <p>
            Each player has the same eleven pieces in their own colour, white or black.
            Every kind of piece moves in its own way, and the sections further down show
            each of them with a diagram.
          </p>
          <PieceList />
        </HelpSection>
        <HelpSection id="goal" title={TITLES.goal}>
          <p>
            The game has no board. Instead the pieces form the hive as they are placed,
            and white always makes the first move.
          </p>
          <p>
            You win by surrounding the queen bee of your opponent on all six sides, and
            pieces of both colours count towards surrounding it.
          </p>
          <Diagrams ids={["goal"]} />
        </HelpSection>
        <HelpSection id="placement" title={TITLES.placement}>
          <p>
            On each turn you either place a piece from your hand or move one of your
            pieces on the board. The first piece goes anywhere, and the second piece of
            the game goes next to it.
          </p>
          <p>
            From then on a new piece must touch at least one piece of your own colour and
            no piece of the opponent. A placed piece stays on the board for the rest of
            the game and is never taken back into your hand.
          </p>
          <p>
            Your queen must be placed by your fourth turn at the latest, and until it is
            on the board none of your pieces may move.
          </p>
          <Diagrams
            ids={[
              "placement-second",
              "placement-own-colour",
              "placement-queen",
              "placement-no-moves",
            ]}
          />
        </HelpSection>
        <HelpSection id="one-hive" title={TITLES["one-hive"]}>
          <p>
            The pieces must always form one connected hive. A piece may not move when
            taking it away would split the hive, not even for a moment while it is lifted
            and on its way.
          </p>
          <Diagrams ids={["one-hive-split", "one-hive-end"]} />
        </HelpSection>
        <HelpSection id="freedom" title={TITLES.freedom}>
          <p>
            Pieces other than the grasshopper and a climbing beetle slide over the table.
            A piece cannot squeeze through a gate, a gap between two pieces that is too
            narrow to slide through, and it must stay in touch with the hive while it
            slides.
          </p>
          <Diagrams ids={["freedom-gate"]} />
        </HelpSection>
        <HelpSection id="queen" title={TITLES.queen}>
          <p>The queen bee slides one hex per turn, to an empty hex next to it.</p>
          <Diagrams ids={["queen"]} />
        </HelpSection>
        <HelpSection id="beetle" title={TITLES.beetle}>
          <p>
            The beetle moves one hex per turn like the queen, but it may also climb on top
            of the hive, move along the top and climb down into a gap.
          </p>
          <p>
            Only the top piece of a stack can move, so a piece with a beetle on top stays
            where it is until the beetle leaves. While the beetle is on top, the stack
            counts as the colour of the beetle when new pieces are placed.
          </p>
          <Diagrams ids={["beetle-climb", "beetle-pin", "beetle-colour"]} />
        </HelpSection>
        <HelpSection id="grasshopper" title={TITLES.grasshopper}>
          <p>
            The grasshopper jumps in a straight line over at least one piece and lands on
            the first empty hex behind them. Because it jumps instead of sliding, gates do
            not stop it.
          </p>
          <Diagrams ids={["grasshopper"]} />
        </HelpSection>
        <HelpSection id="spider" title={TITLES.spider}>
          <p>
            The spider slides exactly three hexes, staying in touch with the hive, and may
            not go back along its own path.
          </p>
          <Diagrams ids={["spider"]} />
        </HelpSection>
        <HelpSection id="ant" title={TITLES.ant}>
          <p>
            The soldier ant slides any number of hexes around the hive, as long as it can
            slide there.
          </p>
          <Diagrams ids={["ant"]} />
        </HelpSection>
        <HelpSection id="passing" title={TITLES.passing}>
          <p>
            When you can neither place nor move a piece, you must pass your turn. Passing
            is only allowed when no move is possible.
          </p>
          <Diagrams ids={["pass"]} />
        </HelpSection>
        {/* Repetition draws belong here once WP 30 adds them to the engine. */}
        <HelpSection id="end" title={TITLES.end}>
          <p>
            The game ends as soon as a queen is surrounded on all six sides, and the
            player whose queen is surrounded loses. When one move surrounds both queens at
            once, the game is a draw.
          </p>
          <Diagrams ids={["draw"]} />
        </HelpSection>
      </SearchableSections>
    </div>
  );
}
