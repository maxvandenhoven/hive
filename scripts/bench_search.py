"""Measure completed search depth on identical positions at a fixed wall time budget."""

import argparse
import json
import platform
import statistics
from pathlib import Path

from hive.agents.factory import AgentSpec, build_agent
from hive.agents.testing import LocalTurnContext
from hive.bench import PerftSuite
from hive.engine.rules import Rules


def main() -> None:
    """Write raw depth observations and their summaries for reproducible comparisons."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", default="{}")
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--position", action="append")
    parser.add_argument("--default-rules", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    suite = PerftSuite.load(Path("tests/data/perft/base.json"))
    rules = Rules() if args.default_rules else suite.rules
    observations = []

    for repeat in range(args.repeat):
        for name in args.position or ("start", "long_hive", "ant_moves", "beetle_gate"):
            agent = build_agent(
                spec=AgentSpec(kind="negamax", params=json.loads(args.params)),
                rules=rules,
                seed=0,
            )
            state = suite.position(name).state(rules)
            turn = LocalTurnContext(budget_s=args.budget)
            turn.run(agent=agent, state=state)
            info = turn.infos[-1] if turn.infos else {}
            observations.append({"repeat": repeat, "position": name, **info})

    depths = [depth for row in observations if isinstance(depth := row.get("depth"), int)]
    speeds = [speed for row in observations if isinstance(speed := row.get("nps"), int)]
    result = {
        "machine": platform.platform(),
        "params": json.loads(args.params),
        "default_rules": args.default_rules,
        "budget_s": args.budget,
        "repeat": args.repeat,
        "mean_depth": statistics.mean(depths),
        "max_depth": max(depths),
        "mean_nodes_per_s": statistics.mean(speeds),
        "observations": observations,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
