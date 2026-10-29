import { useMemo } from "react";

import { BoardDiagram } from "@/components/help/BoardDiagram";
import { toBoardView } from "@/lib/moves";
import { describeDiagram, diagramSteps, rulesDiagram } from "@/lib/rulesDiagrams";

/**
 * A rule diagram checked against the engine, with the allowed targets in green, the
 * forbidden ones crossed out in red, and the steps of the move when it has a path.
 */
export function RulesDiagram({ id }: { id: string }) {
  const diagram = rulesDiagram(id);
  const board = useMemo(() => toBoardView(diagram.board), [diagram]);
  const steps = useMemo(() => diagramSteps(board, diagram.path), [board, diagram]);

  return (
    <div data-diagram={diagram.id}>
      <BoardDiagram
        board={board}
        title={describeDiagram(diagram)}
        caption={diagram.caption}
        highlights={diagram.allowed}
        selected={diagram.source}
        forbidden={diagram.forbidden}
        steps={steps}
      />
    </div>
  );
}
