"""Tune configurations against the previous champion using production gauntlets."""

import argparse
import dataclasses
import gzip
import hashlib
import json
import logging
import subprocess
from pathlib import Path

from hive import _core
from hive.agents.factory import AgentSpec
from hive.match.champion import FAST_CHAMPION_GATE, STRICT_CHAMPION_GATE, ChampionTrial

logger = logging.getLogger(__name__)


def main() -> None:
    """Run an immutable trial batch and optionally promote one confirmed candidate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--champion", type=Path, default=Path("configs/evaluation/champion.json")
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=8)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument(
        "--phase", choices=("screening", "confirmation"), default="screening"
    )
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument(
        "--gate",
        choices=("strict", "fast"),
        default="strict",
        help="Promotion evidence: strict (100 pairs, 10 s, Hoeffding) or fast (50 "
        "pairs, 1 s, normal bound).",
    )
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    original = args.champion.read_bytes()
    manifest = json.loads(original)
    incumbent = AgentSpec.from_json(manifest["spec"])
    candidates = json.loads(args.candidates.read_text())

    if not candidates or (
        args.promote and (len(candidates) != 1 or args.phase != "confirmation")
    ):
        parser.error(
            "Promotion requires one candidate and a predeclared confirmation trial."
        )

    gate = STRICT_CHAMPION_GATE if args.gate == "strict" else FAST_CHAMPION_GATE

    if not 0 < args.alpha < 1:
        parser.error("Alpha must be between zero and one.")

    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True))
    args.out.mkdir(parents=True, exist_ok=False)
    batch = {
        "champion": manifest,
        "champion_sha256": hashlib.sha256(original).hexdigest(),
        "revision": revision,
        "engine_sha256": hashlib.sha256(Path(_core.__file__).read_bytes()).hexdigest(),
        "dirty": dirty,
        "phase": args.phase,
        "seed": args.seed,
        "pairs": args.pairs,
        "budget_s": args.budget,
        "alpha": args.alpha,
        "gate": args.gate,
        "max_turns": args.max_turns,
        "results": {},
    }
    (args.out / "plan.json").write_text(
        json.dumps({**batch, "candidates": candidates}, indent=2) + "\n"
    )

    for index, (label, overrides) in enumerate(candidates.items()):
        spec = AgentSpec(kind="negamax", params={**incumbent.params, **overrides})
        spec.validate_params()
        trial = ChampionTrial(
            champion=incumbent,
            candidate=spec,
            pairs=args.pairs,
            seed=args.seed,
            budget_s=args.budget,
            jobs=args.jobs,
            max_turns=args.max_turns,
        )
        report = trial.config().run()
        assessment = ChampionTrial.assessment(report=report, alpha=args.alpha, gate=gate)
        report_path = args.out / f"candidate-{index}.json.gz"
        with gzip.open(report_path, "wt") as stream:
            json.dump(report.to_json(), stream)

        batch["results"][label] = {
            "spec": spec.to_json(),
            "assessment": dataclasses.asdict(assessment),
            "report": report_path.name,
        }
        (args.out / "summary.json").write_text(json.dumps(batch, indent=2) + "\n")
        logger.info(
            "%s: score %.3f (+%d =%d -%d, %d capped), lower bound %.3f, eligible %s; "
            "depth %.2f vs %.2f, knodes/s %.0f vs %.0f (candidate vs champion), %.0f s",
            label,
            assessment.score,
            assessment.wins,
            assessment.draws,
            assessment.losses,
            assessment.turn_caps,
            assessment.lower_bound,
            assessment.eligible,
            assessment.candidate_mean_depth or 0.0,
            assessment.champion_mean_depth or 0.0,
            (assessment.candidate_nodes_per_s or 0.0) / 1000,
            (assessment.champion_nodes_per_s or 0.0) / 1000,
            report.duration_s,
        )

        if args.promote:
            if not assessment.eligible or dirty:
                parser.error(
                    "Promotion requires passing evidence and a clean committed engine."
                )

            if args.champion.read_bytes() != original:
                parser.error(
                    "Champion changed during the trial; refusing stale promotion."
                )

            archive = args.champion.parent / "history"
            archive.mkdir(exist_ok=True)
            archived = archive / f"generation-{manifest['generation']}.json"

            with archived.open("xb") as stream:
                stream.write(original)

            updated = {
                "generation": manifest["generation"] + 1,
                "name": label,
                "source_revision": revision,
                "spec": spec.to_json(),
                "evidence": str(args.out / "summary.json"),
            }
            temporary = args.champion.with_suffix(".next.json")
            temporary.write_text(json.dumps(updated, indent=2) + "\n")
            temporary.replace(args.champion)


if __name__ == "__main__":
    main()
