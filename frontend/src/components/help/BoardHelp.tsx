import { useMemo } from "react";

import { BOARD_MARKS } from "@/components/board/boardMarks";
import { BoardMarkList } from "@/components/board/BoardLegend";
import { BoardDiagram } from "@/components/help/BoardDiagram";
import { toBoardView } from "@/lib/moves";
import { rulesDiagram } from "@/lib/rulesDiagrams";

/**
 * The colours and marks of the board, as the legend of the game page with every
 * description, and small boards drawn by the real renderer that show the marks in play.
 * The positions are those of the rule diagrams.
 */
export function BoardHelp() {
  const ant = rulesDiagram("ant");
  const beetle = rulesDiagram("beetle-climb");
  const stack = rulesDiagram("beetle-pin");
  const antBoard = useMemo(() => toBoardView(ant.board), [ant]);
  const beetleBoard = useMemo(() => toBoardView(beetle.board), [beetle]);
  const stackBoard = useMemo(() => toBoardView(stack.board), [stack]);

  return (
    <>
      <p>
        Each colour on the board has one meaning, and each mark also has its own shape, so
        it reads without colour too. The Key button at the bottom left of the board lists
        the marks on the board first.
      </p>
      <BoardMarkList title="The marks" marks={BOARD_MARKS} describeOnPhone />
      <div className="grid gap-6 sm:grid-cols-2">
        <BoardDiagram
          board={antBoard}
          title="Choosing a move"
          caption="The white ant is raised with a blue ring, so it can move. Once you tap it, the green hexes show where it can go."
          movable={[[-1, 0]]}
          selected={[-1, 0]}
          highlights={ant.allowed}
        />
        <BoardDiagram
          board={beetleBoard}
          title="Climbing"
          caption="A green ring on a tile means the selected beetle can climb on top of it."
          movable={[[0, 0]]}
          selected={[0, 0]}
          highlights={beetle.allowed}
        />
        <BoardDiagram
          board={antBoard}
          title="Last move and a suggestion"
          caption="The honey outline shows the last move. A purple arrow from a ringed piece to a double ring is a move an agent suggests, its best move while thinking, the move to make on the table or a hint."
          lastMove={{ from: null, to: [2, 0] }}
          proposedMove={{ from: [-1, 0], to: [2, -1] }}
        />
        <BoardDiagram
          board={stackBoard}
          title="Stacks"
          caption="A number on a tile counts the pieces in its stack, and the pieces below peek out. Tap a stack to list its pieces from the top."
        />
      </div>
    </>
  );
}
