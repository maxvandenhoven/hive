import { ArrowLeftIcon } from "lucide-react";
import { Link } from "react-router";

import { HelpSection } from "@/components/help/HelpSection";
import { RulesDiagram } from "@/components/help/RulesDiagram";
import { SearchableSections } from "@/components/help/SearchableSections";
import { Button } from "@/components/ui/button";
import { RULES_SECTIONS, type RulesSection } from "@/lib/help";

const TITLES = Object.fromEntries(
  RULES_SECTIONS.map(({ id, title }) => [id, title]),
) as Record<RulesSection, string>;

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
        In the diagrams a blue outline marks the piece that moves, green hexes are where
        it may go and crossed out red hexes are where it may not. Every diagram is checked
        against the engine of this app.
      </p>
      <SearchableSections label="Search the rules">
        <HelpSection id="goal" title={TITLES.goal}>
          <p>
            Each player has eleven pieces. One queen bee, two beetles, three grasshoppers,
            two spiders and three soldier ants. There is no board, the pieces themselves
            form the hive. White starts.
          </p>
          <p>
            You win by surrounding the queen of your opponent on all six sides. Pieces of
            both colours count.
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
            no piece of the opponent. Once on the board, a piece is never taken back into
            your hand.
          </p>
          <p>
            Your queen must be placed by your fourth turn. Until it is on the board, none
            of your pieces may move.
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
          <p>The queen bee moves one hex per turn.</p>
          <Diagrams ids={["queen"]} />
        </HelpSection>
        <HelpSection id="beetle" title={TITLES.beetle}>
          <p>
            The beetle moves one hex per turn, and it may climb on top of the hive and
            move along it, also down into a gap. Only the top piece of a stack can move.
          </p>
          <p>
            A piece with a beetle on top cannot move, and the stack counts as the colour
            of the beetle when placing new pieces.
          </p>
          <Diagrams ids={["beetle-climb", "beetle-pin", "beetle-colour"]} />
        </HelpSection>
        <HelpSection id="grasshopper" title={TITLES.grasshopper}>
          <p>
            The grasshopper jumps in a straight line over at least one piece and lands on
            the first empty hex. It ignores gates.
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
            When you can neither place nor move a piece, you must pass. You may only pass
            when no move is possible.
          </p>
          <Diagrams ids={["pass"]} />
        </HelpSection>
        {/* Repetition draws belong here once WP 30 adds them to the engine. */}
        <HelpSection id="end" title={TITLES.end}>
          <p>
            A player whose queen is surrounded on all six sides loses. When a move
            surrounds both queens at once, the game is a draw.
          </p>
          <Diagrams ids={["draw"]} />
        </HelpSection>
      </SearchableSections>
    </div>
  );
}
