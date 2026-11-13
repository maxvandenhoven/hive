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
| tempo | Bonus for the side to move, against the odd-even effect of the depth |
| mobile_queen … mobile_ant | Per type: top, unpinned pieces that can make a first step (sliders need a free slide), once their queen is placed |
| placement_cells | Free cells next to own and not next to enemy tops, for players with a hand |

Structural terms count integers per player and multiply by the weights at the end, so the
score does not depend on the board scan order, which depends on the move history (an
earlier float version broke the score parity of helper threads).

## Configurable search

Every refinement is off by default, so the parity tests of the plain search still hold.

| Parameter | Effect |
|---|---|
| table_deeper_hits | Reuse table entries searched deeper than the node needs |
| late_move_reductions | N: moves after the first N of inner nodes (depth ≥ 3) are scouted one ply shallower; improvements are searched again at full depth (needs PVS) |
| null_move_reduction | R: at scout nodes with depth ≥ R + 2, own queen placed with ≤ 3 neighbours and static score ≥ beta, pass and search R + 1 plies shallower; cut off if still ≥ beta |
| queen_attack_ordering | Order moves onto or next to the enemy queen right after the killer moves |

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

## Fast ratchet (session protocol)

The strict gate needs hours of ten-second games, so day-to-day tuning uses a fast gate
(`--gate fast`, `FAST_CHAMPION_GATE`): at least 50 opening pairs at one second per move,
promoting when the one-sided 95% normal lower bound of the pair scores exceeds 0.5. Pair
scores (the candidate's points over both colours of one opening) are independent, so the
normal approximation of their mean is appropriate at 50 pairs; Hoeffding's bound is
reported too. One trial takes about ten minutes with eight concurrent matches of two
threads on the 16-thread development machine (both sides share the same load).

1. Screen candidates at 0.25 s with 24 pairs on development seeds (~1.5 min each).
2. Run the best one or two at 1 s with 50 pairs and `--gate fast --phase confirmation
   --promote` on a fresh seed range. A promotion makes the candidate the next champion.
3. Report speed for every change: `scripts/bench_search.py --budget 1` on the fixed
   positions (mean completed depth, nodes/s) and the in-game depth and nodes/s of both
   sides from the trial.

Trials run from a clean git worktree at a committed revision, so rebuilding the main
checkout cannot disturb running workers and every report names a clean revision.
The strict ten-second gate remains the release check before relying on a champion.

## Results log

Speed: `bench_search.py --budget 1 --repeat 2`, two threads, on the four fixed positions
(no other load). Generation 0 (b90be45 config): mean depth 8.25, max 10, 7.8 M nodes/s.

| Change (overlay on the champion) | Depth @1 s | knodes/s |
|---|---|---|
| table_deeper_hits | 8.25 | 7688 |
| late_move_reductions 3 | 10.12 | 4244 |
| null_move_reduction 2 | 10.25 | 4464 |
| queen_attack_ordering | 8.25 | 7589 |
| all four search refinements | 12.88 | 4615 |
| structure (pinned 0.025, free ants 0.25, beetles 0.25) | 7.38 | 2542 |
| mobile pieces (ant 0.3, beetle/queen 0.2, spider/grasshopper 0.1) | 7.50 | 2540 |
| placement_cells 0.05 | 8.00 | 5912 |

Trials against the champion (score = candidate points per game; W-D-L; depth and
knodes/s are in-game means, candidate vs champion):

| Trial | Candidate | Score | W-D-L (caps) | Normal lower | Depth cand/champ | knodes/s cand/champ |
|---|---|---|---|---|---|---|
| screen-search-v1 (0.25 s, 24 pairs, seed 100, gen 0) | table_deeper_hits | 0.490 | 18-11-19 (11) | 0.409 | 5.64 / 5.71 | 2448 / 2400 |
| | late_move_reductions 3 | 0.438 | 16-10-22 (9) | 0.338 | 6.67 / 5.65 | 1773 / 2192 |
| | null_move_reduction 2 | 0.583 | 23-10-15 (10) | 0.506 | 6.26 / 5.68 | 2014 / 2106 |
| | queen_attack_ordering | 0.500 | 16-16-16 (16) | 0.457 | 5.86 / 5.87 | 2493 / 2635 |
| | all four search refinements | 0.521 | 19-12-17 (11) | 0.413 | 7.69 / 5.71 | 1730 / 2600 |
| | structure | 0.729 | 29-12-7 (12) | 0.660 | 4.48 / 5.81 | 1052 / 2726 |
| | structure + all four refinements | 0.792 | 35-6-7 (6) | 0.704 | 5.74 / 5.77 | 991 / 2886 |

Lesson: evaluation knowledge beats raw depth. LMR alone gains a ply yet loses games, and
the structure terms win while searching 1.3 plies shallower; combined, the refinements
win back the depth the evaluation costs.

### Generation 1 (promoted)

`confirm-gen1` (1 s, 50 pairs, seeds 30000–30049, fast gate, revision 4204290):
structure + all four search refinements scored **0.845** against generation 0,
81-7-12 with 7 turn caps, normal lower bound 0.795. In-game depth 7.00 vs 6.38 at
899 vs 2211 knodes/s. Generation 1 = pinned_material 0.025, free_ants 0.25,
beetle_control 0.25, table_deeper_hits, late_move_reductions 3, null_move_reduction 2,
queen_attack_ordering (on the b90be45 search settings).

| Trial | Candidate | Score | W-D-L (caps) | Normal lower | Depth cand/champ | knodes/s cand/champ |
|---|---|---|---|---|---|---|
| screen-gen1-v1 (0.25 s, 24 pairs, seed 200, gen 1) | late_move_reductions 0 | 0.417 | 14-12-22 (9) | 0.299 | 5.32 / 6.28 | 924 / 810 |
| | late_move_reductions 6 | 0.625 | 25-10-13 (9) | 0.523 | 6.06 / 6.38 | 887 / 855 |
| | queen_threat_extension | 0.479 | 17-12-19 (11) | 0.387 | 5.82 / 6.56 | 904 / 872 |
| | null_move_reduction 3 | 0.427 | 15-11-22 (9) | 0.312 | 6.34 / 6.26 | 876 / 872 |
| | mobile pieces (free_ants 0) | 0.542 | 18-16-14 (14) | 0.461 | 6.71 / 6.82 | 922 / 890 |
| | placement_cells 0.05 | 0.396 | 13-12-23 (11) | 0.314 | 6.30 / 6.62 | 734 / 844 |
| | queen_danger 0.1 | 0.417 | 13-14-21 (11) | 0.325 | 6.32 / 6.27 | 833 / 909 |
| | tempo 0.3 | 0.635 | 22-17-9 (15) | 0.533 | 6.65 / 6.52 | 921 / 832 |
| | beetle_control 0.5 | 0.521 | 17-16-15 (14) | 0.432 | 6.57 / 6.68 | 887 / 875 |
| | pinned_material 0.05 | 0.490 | 16-15-17 (14) | 0.399 | 6.46 / 6.53 | 902 / 834 |

### Generation 2 (promoted)

`confirm-gen2` (1 s, 50 pairs, seeds 30100–30149, fast gate, revision 2858b2c): tempo 0.3
and late_move_reductions 6 on generation 1 scored **0.590**, 42-34-24 with 26 turn caps,
normal lower bound 0.536. Depth 7.78 vs 7.89 at 883 vs 822 knodes/s. A quarter of the
games now reach the 60-turn cap: the stronger agents defend well but convert poorly.
