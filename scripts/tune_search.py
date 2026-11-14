"""Screen evaluator weights with timed, colour-paired games from seeded openings.

Use disjoint seeds and a larger budget to validate finalists. The material terms are
negatives in the base game; tune on-board material and keep hand weight zero.
"""

import argparse
import json
import logging
import os
import random
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hive.agents.factory import AgentSpec, build_agent
from hive.agents.testing import LocalTurnContext
from hive.engine.rules import Rules
from hive.engine.state import Player

logger = logging.getLogger(__name__)


@dataclass
class TuningGame:
    """One colour of a reproducible opening pair against a fixed opponent."""

    label: str
    params: dict[str, Any]
    opponent: dict[str, Any]
    seed: int
    colour: int
    budget: float
    max_plies: int

    def play(self) -> dict[str, Any]:
        """Play a legal game and keep the opening, moves and depth measurements."""
        rules = Rules()
        state = rules.create_initial_state()
        rng = random.Random(self.seed)
        opening = []

        for _ in range(8):
            move = rng.choice(rules.legal_moves(state))
            rules.apply_checked_move(state=state, move=move)
            opening.append(None if move is None else move.to_json())

        candidate = list(Player)[self.colour]
        agents = {
            player: build_agent(
                spec=AgentSpec(
                    kind="negamax",
                    params=self.params if player == candidate else self.opponent,
                ),
                rules=rules,
                seed=self.seed,
            )
            for player in Player
        }
        decisions = []

        while not rules.is_finished(state) and state.current_ply < self.max_plies:
            player = state.current_player
            turn = LocalTurnContext(budget_s=self.budget)
            move = turn.run(agent=agents[player], state=state)
            rules.apply_checked_move(state=state, move=move)
            info = turn.infos[-1] if turn.infos else {}
            decisions.append(
                {
                    "candidate": player == candidate,
                    "depth": info.get("depth"),
                    "move": None if move is None else move.to_json(),
                }
            )

        winners = rules.winners(state)
        score = (
            0.5 if winners is None or len(winners) != 1 else float(candidate in winners)
        )
        return {
            "label": self.label,
            "seed": self.seed,
            "colour": self.colour,
            "score": score,
            "capped": winners is None,
            "opening": opening,
            "decisions": decisions,
        }


def play_game(game: TuningGame) -> dict[str, Any]:
    """Run one game in a process pool."""
    return game.play()


def main() -> None:
    """Run a candidate file against a fixed opponent and save every observation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--opponent", default="{}")
    parser.add_argument("--budget", type=float, default=0.1)
    parser.add_argument("--pairs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-plies", type=int, default=120)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    candidates = json.loads(args.candidates.read_text())
    opponent = json.loads(args.opponent)
    max_threads = max(
        params.get("threads", 1) for params in [opponent, *candidates.values()]
    )

    if args.jobs * max_threads > (os.cpu_count() or 1):
        parser.error("Search threads times jobs must fit the available CPUs.")

    if args.budget <= 0 or args.pairs < 1 or args.jobs < 1 or args.max_plies <= 8:
        parser.error("Use positive budgets, pairs and jobs, and more than eight plies.")

    games = [
        TuningGame(label, params, opponent, seed, colour, args.budget, args.max_plies)
        for seed in range(args.seed, args.seed + args.pairs)
        for label, params in candidates.items()
        for colour in range(2)
    ]
    rows = []

    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for row in pool.map(play_game, games):
            rows.append(row)
            logger.info(
                "%d/%d %s: %.1f", len(rows), len(games), row["label"], row["score"]
            )
            args.out.write_text(
                json.dumps(
                    {
                        "candidates": candidates,
                        "opponent": opponent,
                        "budget_s": args.budget,
                        "pairs": args.pairs,
                        "seed": args.seed,
                        "max_plies": args.max_plies,
                        "jobs": args.jobs,
                        "games": rows,
                    },
                    indent=2,
                )
                + "\n"
            )


if __name__ == "__main__":
    main()
