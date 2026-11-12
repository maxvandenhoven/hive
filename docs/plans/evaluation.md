# Evaluation tuning and the champion ratchet

The primary objective is stronger play at ten seconds per move on two search threads.
Depth and nodes/second explain costs but do not determine promotion. No result guarantees
a win against a particular human. Relative engine strength is not a human Elo rating.

## Baseline and scope

`configs/evaluation/baseline.json` preserves the generation-zero specification from
`b90be45` (#90): queen safety 1, other evaluation weights zero, 32 MB table, aspiration
0.5, PVS enabled and two threads. `champion.json` initially names that same champion.
The original source remains available at that commit. This ratchet compares **configs
within the current engine**, not separately compiled historical engines. Zero new weights
preserve the old evaluation, and search score parity tests guard that path. Comparing a
future search/engine rewrite requires isolated historical binaries, not merely these
config files. Reports record the source revision, dirty status and extension SHA-256.

Measured #90 baseline: fixed-suite mean/maximum depth 8.25/10 at one second and 10/11 at
ten seconds. The app's normal opening reaches 11 at ten seconds. Its absolute human
strength is unknown. The previous 152-game weight sweep did not confirm an improvement.

## Configurable evaluation

All terms are antisymmetric: positive scores favour the requested player. Every new
weight defaults to zero and disabled terms are skipped. Preserve queen safety at 1 when
tuning to fix the score scale, since aspiration windows use that scale too.

| Parameter | Meaning of positive weight |
|---|---|
| queen_safety | Prefer fewer occupied neighbours around own queen |
| queen_danger | Square those counts, penalizing dangerous crowding nonlinearly |
| queen_escape | Prefer more actual legal queen moves; covered/pinned queens have none |
| pinned_material | Penalize own covered or articulation-pinned material, by piece value |
| free_ants | Reward uncovered, unpinned ants once their owner's queen is placed |
| beetle_control | Reward elevated top beetles; double credit over an enemy queen |
| mobility | Compare full legal move counts; expensive because both sides generate moves |
| positioning | Compare owned top pieces adjacent to the enemy queen |
| material_on_board / material_in_hand | Existing piece-value balance terms |

`free_ants` is a cheap structural proxy, not an exact movement count: an unpinned ant
can still be blocked by gates. Likewise pinned material measures covering/connectivity,
not every form of immobility. Structural terms share one articulation computation and
board traversal. Queen escape uses the movement rules, restoring the player and board.
The material terms are redundant opposites in the base game; only tune one of them.

Weights are normal agent params, available through YAML/JSON, the factory and the API.
`configs/evaluation/candidates.json` is an editable initial sweep; no code changes are
needed to add combinations. Candidates overlay the complete incumbent configuration,
so all unchanged search settings and weights stay fixed. Explicit zero disables a term.

## Trial protocol

`ChampionTrial` builds a two-participant `GauntletConfig`, which uses `MatchRunner` and
persistent `AgentWorker` processes. It inherits real deadlines, legal-submission checks,
worker failure reporting and decision metrics. Opening moves are now part of match
records; replay reconstructs the opening before the timed decisions. Existing records
without openings continue to load.

Each independently seeded eight-ply legal, nonterminal opening is played in both
colours. Match seeds alone are insufficient because equal-score search is deterministic.
Opening suites should ultimately also include reviewed human/strong-engine positions;
random openings provide diversity but are not a complete model of human play. Explicit
`GauntletConfig.openings` supports such suites. Both seats have equal time/thread budgets;
concurrent matches times search threads must fit the available CPUs.

Use disjoint seed ranges for development (0–9999), validation (10000–19999), and final
confirmation (20000 onward). Never tune using a final confirmation result and then reuse
that same set as confirmation. Allocate a fresh range for each attempt. The plan is
written before any game; every match, opening, move, depth and flag is retained.

Score = (wins + 0.5 draws) / games. Turn caps count as draws for this protocol and are
reported separately. Do not adjudicate a win from either agent's own evaluation. Keep
rules and caps fixed within comparisons; introducing repetition is a separate change.

Screen cheaply, then validate at one second. Final promotion requires a **predeclared**
comparison at ten seconds with at least 100 distinct opening pairs (200 games), complete
results and no worker/overrun/illegal-submission flags. The one-sided lower score bound
must exceed 0.5. We use Hoeffding's bound on independent opening-pair scores in [0,1]:
`lower = mean - sqrt(log(1/alpha)/(2*pairs))`. This is conservative and treats the two
colours as one sample rather than incorrectly assuming independent games. At 100 pairs
and alpha 0.05 a score just above 62.24% is required. A small gain can require many more
games; an inconclusive trial does not promote. Fix sample size and alpha before playing.

Repeated attempts need an error budget: for attempt k, allocate e.g.
`alpha_k = 0.05 / (k*(k+1))`, whose sum is 0.05. `--alpha` records the predeclared value;
the operator must track attempt numbers and fresh holdouts. The tool does not implement
SPRT or automatic protection against selective reporting. Do not repeatedly peek and
extend a fixed-sample trial until it passes.

Before release, also play the candidate against the immutable baseline and earlier
champions, and check verified tactical fixtures. These are mandatory review checks,
not yet automatic promotion gates. They help catch opponent-specific and nontransitive
regressions. Only the immediately previous champion comparison is automated by the CLI.

## Commands and promotion

```sh
uv run python scripts/tune_champion.py \
  --candidates configs/evaluation/candidates.json --seed 0 --pairs 8 \
  --budget 0.1 --jobs 4 --max-turns 40 --out reports/evaluation/screen-v1

# finalists.json maps candidate names to parameter overrides.
uv run python scripts/tune_champion.py --candidates finalists.json \
  --seed 10000 --pairs 16 --budget 1 --jobs 4 \
  --out reports/evaluation/validation-v1

# One candidate only, clean committed code, a fresh predeclared confirmation set.
uv run python scripts/tune_champion.py --candidates winner.json \
  --phase confirmation --seed 20000 --pairs 100 --budget 10 --jobs 4 \
  --out reports/evaluation/confirmation-v1 --promote
```

The output directory must be new: evidence is never overwritten. `--promote` refuses
screening batches, multiple candidates, failed gates, dirty source or a champion changed
during the run. On success it archives the incumbent under `configs/evaluation/history/`
and replaces `champion.json` with the candidate, source revision and evidence path.
Commit that manifest and the evidence together. Failed/inconclusive candidates leave the
champion unchanged. Thus each promoted configuration becomes the next fixed opponent.
