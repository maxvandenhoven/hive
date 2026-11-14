# Golden fixtures

These files pin the stored and served formats and one seeded game, recorded on `main` at
d58e7de before the cleanup round (`docs/plans/cleanup.md`, WP 46). `tests/test_golden.py`
checks that the code reads and writes each file unchanged, or plays the same game again.

| File | Pins | Test |
|---|---|---|
| `gauntlet_report.json` | A gauntlet report (version 2) with replays, and the statistics recomputed from them | `TestGauntletReport` |
| `champion_spec.json` | The agent spec of the generation 5 champion, from `configs/evaluation/champion.json` | `TestChampionSpec` |
| `players.json` | The `white_player` and `black_player` JSON values as the `game` table stores them: a person, a person with a hint agent, an agent | `test_stored_players_round_trip` |
| `openapi.json` | The output of `hive openapi`, compared without `info.version` | `test_openapi_output` |
| `pinned_match.json` | A match between two depth-limited agents with seed 46: every move, the seat seeds, the last search report of every decision (without `nps`) and the outcome | `TestPinnedMatch` |

A change that alters one of these on purpose regenerates the file in the same pull
request and says why, so the diff shows the change. From the repository root:

```sh
uv run hive gauntlet --agent random --agent "{kind: negamax, label: nm1, params: {depth: 1}}" \
  --games-per-pair 2 --budget 1 --max-turns 6 --seed 46 --jobs 2 --replays \
  --out tests/data/golden/gauntlet_report.json
uv run hive openapi --output tests/data/golden/openapi.json
uv run hive play \
  --white "{kind: negamax, label: champion-d3, params: {depth: 3, queen_safety: 0.75, pinned_material: 0.05, beetle_control: 0.5, alpha_beta: true, tempo: 0.3, mobile_ant: 0.3, mobile_beetle: 0.15, mobile_queen: 0.2, mobile_spider: 0.1, mobile_grasshopper: 0.1, repetition_draws: true}}" \
  --black "{kind: negamax, label: nm2, params: {depth: 2}}" \
  --budget 10 --max-turns 60 --seed 46 --out tests/data/golden/pinned_match.json
```

`hive play` and `hive gauntlet` write no final newline, so add one after regenerating
(the `end-of-file-fixer` hook does it on commit). The pinned
match must not change at all in a refactor: both agents stop at their depth limit long
before the ten-second budget (the slowest decision took 9 ms), so its moves do not depend
on timing. The champion spec and the players are written by hand.
