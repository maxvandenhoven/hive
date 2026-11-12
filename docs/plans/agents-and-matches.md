# Agents, matches and gauntlets

Agents choose moves. The match layer runs agents under a time budget in worker processes,
and the gauntlet layer runs many timed matches between parameterized agents for offline
evaluation. The design is adapted from the `shed` project
(<https://github.com/maxvandenhoven/shed>, see `src/shed/agents/base.py`, `match.py`,
`gauntlet.py`), simplified for a perfect-information game.

Packages: `src/hive/agents/` (strategies, no processes or clocks) and `src/hive/match/`
(processes, clocks, records). Dependency direction: `engine ← agents ← match`.

## Agent interface (WP 07)

```python
class TurnContext(Protocol):
    """The whole capability an agent holds during one decision."""

    def submit(self, move: Move | None, *, final: bool = False) -> None: ...
    def remaining_seconds(self) -> float: ...
    def should_stop(self) -> bool: ...
    def info(self, **fields: SearchInfoValue) -> None: ...


class Agent(ABC):
    def __init__(self, rules: Rules, *, seed: int) -> None:
        self.rules = rules
        self.rng = random.Random(seed)

    @abstractmethod
    def think(self, state: GameState, turn: TurnContext) -> None: ...
```

Contract:

- `think` receives a **copy** of the state (the agent may mutate it freely while
  searching) and should **submit a cheap legal move immediately**, then improve on it.
- Submissions are proposals. The runner keeps the latest legal candidate; illegal
  submissions are rejected and logged, leaving the previous candidate standing. A
  `final=True` submission closes the turn.
- `should_stop()` turns true at the deadline (or when the runner cancels). Agents check it
  every N nodes or between iterative-deepening iterations and return. Returning is the
  answer, since the latest candidate is already submitted.
- `info(...)` reports search progress, modelled on UCI `info` lines: `depth`, `nodes`,
  `score`, `pv` (principal variation as serialized moves), `nps`, free-form extras. It
  is fire-and-forget and rate-limited by the context.
- All randomness comes from `self.rng`; the seed is recorded by the runner.
- Perfect information means no `PlayerView`: agents see the full state. Agents receive
  `rules` at construction because they search.
- An agent object lives for the whole match (persistent worker), so it may keep caches
  (transposition tables, loaded models) across turns. `reset()` is optional, called
  between matches when a pooled worker is reused.

Strategies ported in WP 07:

| Kind | Params | Behaviour |
|---|---|---|
| `random` | – | Submits a random legal move with `final=True`. |
| `minimax` | `depth: int \| None` plus the evaluation weights below | Iterative deepening up to `depth` (or until stopped), submitting the best move after each completed depth. |
| `negamax` | same as minimax | Same, negamax formulation. |

`minimax` and `negamax` share `SearchAgent` (`src/hive/agents/search.py`), which runs the
iterative deepening loop:

- Submit a random legal move first (or the only legal move, with `final=True`).
- Search depth 1, 2, 3, and so on. Every node is counted and `should_stop()` is checked
  every `STOP_CHECK_INTERVAL` (32) nodes. A stop discards the unfinished depth, and the
  state is restored on the way out.
- After each completed depth: `info(depth, nodes, score, pv, nps)`, then submit the best
  move. The submission is `final=True` when the depth limit is reached, the game is
  decided (a forced win or loss within the horizon), or the whole tree was searched (no
  line was cut off at the depth limit).
- Finished games score `SEARCH_WIN_SCORE - ply` for a win (so faster wins rank higher),
  the negation for a loss and 0 for a draw.

The alpha-beta variants were removed with the old `choose_move` agents. They come back in
WP 28 on top of this loop.

From WP 45 the search runs in Rust (D31, `rust-core.md` §Search kernel). `SearchAgent`
builds a Rust `Searcher` from its params, and the loop above is the behaviour the port
keeps: the same depths, finishing rules, evaluation terms, `info` fields and node counts
at a fixed depth. The Rust search runs without the GIL and calls `should_stop()` before
each depth and every `STOP_CHECK_INTERVAL` (now 1024) nodes, a fixed count rather than a
time, so a seeded agent stays reproducible under a fake clock. The `random` agent stays
Python: it is no faster in Rust, and its seeded games stay the same.

#### Evaluation weights (no evaluator abstraction)

The old `Evaluator` ABC, with one class per heuristic and a `WeightedCompositeEvaluator`,
is gone for the same reason `Ruleset` became `Rules` (D2, D22): every agent used one
weighted sum, and the only real variation was the weights. The heuristics are methods of
`SearchAgent` (`queen_safety_score`, `mobility_score`, ...), and each weight is a flat
agent parameter next to `depth`:

| Param | Default | Term (from the evaluated player's perspective) |
|---|---|---|
| `queen_safety` | 1.0 | Occupied neighbours of the opponent's queen minus those of the own queen |
| `mobility` | 0.0 | Own legal moves minus the opponent's (slow: generates moves at every leaf) |
| `positioning` | 0.0 | Own top pieces next to the opponent's queen minus the reverse |
| `material_on_board` | 0.0 | Value of own pieces on the board minus the opponent's (`SEARCH_PIECE_VALUES`) |
| `material_in_hand` | 0.0 | Value of own pieces in hand minus the opponent's |
| `alpha_beta` | `true` | Not a term: whether the search prunes with alpha-beta (WP 28), searching the best line of the previous depth first. Same scores, far fewer nodes; among equally scored moves another may be chosen |
| `table_megabytes` | `32` | Negamax transposition table size; zero disables table, killers and history |
| `aspiration_window` | `0` | Initial half-window around the previous score; zero uses a full window. Failed windows widen before a result is reported |
| `principal_variation_search` | `false` | Negamax scouts later moves with a minimal window and re-searches improvements |
| `threads` | `1` | Total negamax threads sharing one table; helpers diversify root order. The main thread reports completed depths and its own node count |

Terms with weight 0 are skipped, so an unused expensive term costs nothing. Flat weights
keep the params of a spec plain numbers next to `depth`, which keeps the API parameter
forms and the weight tuning in WP 28 simple. An agent
with a different kind of evaluation (for example a neural network) is a new agent kind
with its own params, not a new evaluator. Piece values are a module constant; they can
become params if tuning needs them.

### Factory (WP 07)

Agents are made available to configs with a decorator. The parameters of a kind are its
constructor's keyword-only parameters after `seed`, so the signature is the schema:

```python
@register_agent("negamax")
class NegamaxAgent(SearchAgent): ...

class SearchAgent(Agent):
    def __init__(
        self,
        rules: Rules,                                    # injected by the factory
        *,
        seed: int,                                       # injected by the factory
        depth: Annotated[int | None, Field(ge=1)] = None,
        queen_safety: float = 1.0,
        ...
    ) -> None:
        """...

        Args:
            depth: The maximum search depth in plies, or `None` to search until stopped.
            ...
        """
```

- `register_agent` builds a frozen pydantic model from the annotations (constraints go in
  `Annotated[..., Field(...)]`) and defaults, and takes each field description from the
  `Args:` section of the constructor docstring. Required params (no default) and nested
  dataclass params (for example a network shape) work as well. A constructor that does
  not take `rules` first, or has a positional or unannotated agent param, is rejected
  when the class is registered.
- `hive/agents/__init__.py` imports the built-in agent modules, so their decorators run
  whenever anything from `hive.agents` is imported.
- Only registered kinds can be built. There are no import paths in specs, so stored specs
  survive refactors and the API cannot be made to import arbitrary code.

```python
@dataclass(frozen=True, slots=True)
class AgentSpec(JsonCodec):  # to_json() / from_json(data), shape only
    kind: str
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    label: str | None = None   # display name in reports and UI

    @classmethod
    def parse(cls, data: object, *, source: str | None = None) -> AgentSpec: ...
    @classmethod
    def from_yaml(cls, text: str, *, source: str | None = None) -> AgentSpec: ...
    @classmethod
    def load(cls, path: Path) -> AgentSpec: ...
    def validate_params(self, *, source: str | None = None) -> BaseModel: ...

def build_agent(spec: AgentSpec, rules: Rules, *, seed: int) -> Agent: ...
def list_agents() -> list[AgentRegistration]: ...   # kind, description, params schema
```

- `parse` reads user input (CLI, files, API) and also checks the params against the
  registered kind; `from_json` only checks the shape, so stored records with kinds that
  are only registered in workers still load. `AgentRegistration` is itself the JSON the
  API lists (`kind`, `description`, `params_schema`), leaving out the class and model.
- The JSON form is a mapping with `kind`, an optional `label` and optional
  `params`, stored as JSON in records and reports and written as YAML by hand:

  ```yaml
  kind: negamax
  label: nm3
  params:
    depth: 3
    mobility: 0.5
  ```

  `from_yaml` also accepts a bare kind (`random`), so one string works on the command line
  and in a file. `rules` and `seed` are never part of a spec: the runner supplies them, so
  one spec can be replayed with any seed.
- Loading validates the shape, the kind and the params, and raises
  `InvalidAgentSpecError` (a `ValueError`) listing every problem with its path, and the
  file when loaded from one. For example:

  ```
  Invalid agent spec in `configs/nm3.yaml`:
    params.depth: Input should be greater than or equal to 1 (got 0).
    params.depht: Unknown param, expected one of: depth, queen_safety, mobility, ...
  ```

  YAML syntax errors report the line and column. `build_agent` validates again, so a
  spec constructed in code gets the same errors.
- `register_agent` stores an `AgentRegistration` (kind, agent class, params model) in
  `AGENT_REGISTRY`. `list_agents()` returns the registrations, whose `description` is the
  summary line of the class docstring and whose `params_schema` is the JSON schema of the
  params, so the API can list agents and render parameter forms.
- pydantic and PyYAML are core dependencies (not extras), since workers, the CLI and the
  API all build agents.

#### Presets (WP 09 and WP 12)

Tuned agents are stored as spec files in `src/hive/agents/presets/<name>.yaml`, inside the
package so they ship with the wheel and the Docker image (loaded with
`importlib.resources`). The file name is the preset name and the default label; a
`description` key next to the spec says what the agent is like (`AgentPreset`, WP 33). The
gauntlet CLI resolves `--agent VALUE` as a path to a YAML file, then a preset name, then
inline YAML (`random` or `{kind: negamax, params: {depth: 2}}`). The API lists presets
next to `list_agents()`, so the agent picker offers "nm3 (preset)" as well as a custom
form per kind. Weight tuning in WP 28 writes its winners as new presets.

### Testing agents (WP 07)

`src/hive/agents/testing.py` holds `LocalTurnContext`, an in-process `TurnContext` that
records submissions and `info` payloads, and `FakeClock`, which can advance by a fixed
step on every read so deadlines depend on how often an agent checks the time rather than
on machine speed. `tests/agents/test_contract.py` runs every registered kind through the
shared contract: a legal move is submitted even with no time left, thinking returns at
the deadline without submitting after `should_stop()` turned true, the given state is
left unchanged, and a fixed seed gives the same submissions.

## Persistent workers and the runner (WP 08)

Modelled on how UCI chess engines and tournament managers (cutechess-cli) work: one
long-lived engine process per side, cooperative time management, and kills only for
misbehaviour.

```
parent (runner, AgentWorker)                      worker process (one per seat)
────────────────────────────                      ───────────────────────────────
start worker(spec, rules, seed)      ───────────▶ build_agent once (models load here)
wait for IdleMessage(0)              ◀─────────── send IdleMessage(0)
per turn:                                         loop:
  clear stop event
  send ThinkMessage(state, deadline) ───────────▶   receive ThinkMessage
                                                    agent.think(state, PipeTurnContext)
  receive Submission/InfoMessage     ◀───────────     submit / info → pipe
  at deadline: set stop event,                      return → send IdleMessage
  take latest legal candidate
  wait ≤ grace for IdleMessage       ◀───────────
  if no IdleMessage: kill + restart, record failure
```

- Start method `forkserver` (fallback `spawn`), never plain `fork`, so workers never
  inherit parent memory such as open DB connections.
- The stop flag is a `multiprocessing.Event` shared with the worker, so `should_stop()`
  costs nanoseconds.
- The turn ends on time regardless of the worker: at the deadline the parent closes the
  turn with the latest legal candidate. If there is none (the agent never submitted), the
  runner falls back to a seeded random legal move and records it.
- The grace period (default 1 s) only decides whether the worker can be reused. A missed
  grace kills and restarts the worker and is recorded as an agent failure.
- C extension calls that ignore the stop flag (a big model inference) are the only real
  risk; agents keep individual calls short.
- The selection policy (latest legal candidate, final closes the turn, illegal ignored) is
  a pure function over a clock and a message source, testable without processes, like
  `shed.match.select_candidate`.
- An in-process `TurnContext` implementation exists for unit tests of agents.

Implementation notes (WP 08):

- Modules: `match/turn.py` (messages, `PipeTurnContext`, the selection policy
  `CandidateSelection.collect(turn_id, legal_moves, deadline, messages, clock)`),
  `match/worker.py` (`AgentWorker` with `start`, `decide`, `restart`, `close`, usable as a
  context manager), `match/records.py`, `match/runner.py`.
- Messages: the parent sends `ThinkMessage(turn_id, state, deadline)`,
  `ResetMessage(turn_id)` (WP 12) and `None` to close; the worker answers with
  `SubmissionMessage`, `InfoMessage`, `IdleMessage` and `FailedMessage` (together
  `WorkerMessage`). Every message carries the
  turn id, so a late message of an earlier turn is dropped. Turn id 0 is the startup
  handshake: `start()` waits for `IdleMessage(0)` (agent built) or `FailedMessage(0)`
  (raises `AgentWorkerError`), so model loading never counts against the first decision.
- `Rules` pickles by its fields (`__reduce__`), since its read-only `piece_counts` mapping
  cannot be pickled.
- `deadline` is a `time.monotonic` value, which is shared by the processes of one
  machine. `PipeTurnContext.should_stop()` reads only the stop event and final flag, not
  the local clock: the parent sets the event when it closes the turn, so an `IdleMessage` before
  that really means the agent returned on its own, and close reasons stay accurate.
- `info` is rate-limited to one message per 0.1 s; a held-back report is sent before the
  next submission and when the agent returns, so the last report is never lost.
- A `FailedMessage` (the agent raised) keeps the worker; only a missed grace period or
  a dead process (pipe EOF) restarts it. Workers ignore `SIGINT`; the parent closes them.
- The fork server preloads `hive.match.worker`, so a worker starts in about 0.1 s.
- `AgentWorker(preload=[...])` imports modules in the worker before the agent is built, for
  agent kinds registered outside `hive.agents`. Specs still cannot name modules.
  `hive.match.testing` holds the misbehaving test agents (`test-never-submits`,
  `test-illegal`, `test-lingers`, `test-crashes`, `test-counting`); it is only imported
  in workers, so its kinds stay out of `list_agents()` in the test process.
- `MatchRunner(rules, white_spec, black_spec, budget_s, max_turns, seed, grace_s=1.0)`:
  `max_turns` counts turns per player like `Rules.max_turns` (`None` plays to the end).
  Seat seeds are `derive_seed(seed, "white")` and `derive_seed(seed, "black")`, a
  blake2b hash that WP 09 reuses for per-match seeds. `run(decision_callback=...)`
  streams decisions, which the runner appends to `MatchResult.decisions`.
  `AgentWorker.decide(message_callback=...)` streams submissions and info for the API.
- WP 12 adds `AgentWorker.reset()` for pooled workers that move to another game: the
  worker calls `Agent.reset()` and answers `IdleMessage`, and a failed or unanswered
  reset restarts the worker. `AgentWorker.cancel()` sets the stop event from another
  thread, so a running decision closes as soon as the agent returns (`final` with a
  candidate); the next `decide` clears it.
- `hive play --white SPEC --black SPEC --budget 1.0 [--max-turns 100] [--seed 0]
  [--grace 1.0] [--out result.json]` takes a YAML spec file, a preset name or inline YAML
  per seat (`AgentSpec.resolve`) and logs one line per decision and the result.
- Coverage measures worker processes (`concurrency = ["multiprocessing", "thread"]`),
  except for workers that are killed.

### Decision records

Every decision produces a `DecisionRecord`:

| Field | Meaning |
|---|---|
| `ply`, `player`, `agent_label`, `seed` | who decided what, reproducibly |
| `budget_s`, `elapsed_s`, `overrun_s` | time accounting (`overrun_s` = time past deadline until `IdleMessage`) |
| `close_reason` | a `TurnCloseReason`: `final` (final submission, or the agent returned with a candidate), `deadline`, `worker_failed` (agent raised or worker died, latest candidate taken), `no_candidate` (seeded random fallback move, takes precedence) |
| `candidates`, `illegal_submissions` | counts |
| `move` | the applied move (serialized) |
| `last_info` | the last `info` payload (depth, nodes, score, pv) |
| `worker_restarted`, `failure` | safety-net events with a truncated message |

A `MatchResult` holds the rules, both specs, the seed, the budget, the decision records,
the `MatchOutcome` (`win` with a `winner`, `draw`, `turn_cap`) and the
match duration. Its `record` property builds the `GameRecord` from the rules and the
decisions' moves, so the moves are stored once; `thinking_s(player)` sums a seat's
decision times. Both records, and every
gauntlet type, convert with `JsonCodec` like the engine values; derived values such as
rates are written as computed fields and ignored when reading. Reports carry a `version`
(2 since the initial setup is written as `null`).

## Gauntlets (WP 09)

`hive gauntlet` runs scheduled matches between participants and writes a report:

```
hive gauntlet \
  --agent configs/nm3.yaml \
  --agent "{kind: minimax, label: mm3, params: {depth: 3}}" \
  --agent random \
  --games-per-pair 20 --budget 2.0 --max-turns 100 \
  --seed 42 --jobs 4 --out reports/gauntlet-2026-10-24.json [--replays]
```

- Schedule: round robin, each pairing played with both colours equally often.
- Seeds: derived deterministically from the experiment seed per match and seat (as in
  `shed.gauntlet.derive_seed`), so any match can be reproduced.
- Fairness: concurrent matches default to and are capped at `cpu_count` (a match has two
  workers, but only the seat to move thinks), and the CLI refuses higher `--jobs` unless
  `--allow-oversubscribe` is given. From WP 28, an agent with `threads > 1` counts each
  thread against `cpu_count`.
- Output: a versioned JSON document with config, per-participant results (wins, draws,
  losses, win rate with confidence interval, Elo estimate), per-participant decision stats
  (depth reached distribution, nodes/s, timeout rate, overrun distribution, failures,
  illegal submissions), and optionally full replays of every match.
- A short human-readable summary table is logged at the end.
- `hive replay <report> --match N` prints or plots a recorded match using the existing
  plotting helpers.

Implementation notes (WP 09):

- `match/gauntlet.py`: `GauntletConfig(participants, games_per_pair, budget_s, max_turns,
  seed, jobs, grace_s, rules, replays)` validates itself (at least two participants,
  unique display labels, an even `games_per_pair`) and owns `schedule()`, `run()` and
  serialization. `AgentSpec.display_label` is the label, or the kind without one.
- The schedule is played in rounds: every pair plays once per round and swaps colours
  between rounds. The match seed is `derive_seed(seed, "match", index)`, and the runner
  derives the seat seeds from it, so a report reproduces any match from its config.
- Matches run in a `ThreadPoolExecutor` with `jobs` threads, each driving the two worker
  processes of its match; the parent only waits on pipes and checks moves. A worker that
  fails to start cancels the matches that have not started. The cap was `cpu_count // 2`
  in the first plan; it is `cpu_count` because only one seat of a match thinks at a time.
- `GauntletReport` (schema `version` 1) holds the config, one `ParticipantResult` per
  participant, one `MatchSummary` per match and, with `--replays`, every `MatchResult`.
  Draws include games stopped at the turn cap, also counted separately as `turn_caps`.
  The win rate counts a draw as half a win, with a 95% Wilson score interval. Elo is a
  Bradley-Terry fit (minorization-maximization) over all results with one virtual draw
  per pairing, so perfect scores stay finite, centred on a field mean of 0.
- `DecisionStats` per participant: the reported `depth` histogram and mean, the mean
  reported `nps`, counts per close reason, the timeout rate (closed by the deadline),
  elapsed and overrun distributions (mean, p50, p90, max), overruns beyond 0.05 s,
  failures, worker restarts and illegal submissions. A participant is flagged if it has
  failures, overruns, restarts or `no_candidate` decisions. Derived values (rates, mean
  depth, win rate, interval, flag) are written to the JSON and recomputed when loading.
- `hive gauntlet` defaults to two games per pair, `jobs = cpu_count` and
  `reports/gauntlet-<timestamp>.json` (git-ignored). `hive replay` needs a report written
  with `--replays`; `--plot-dir DIR` writes one SVG per ply with `hive.plotting.svg`.
- Presets: `AgentPreset.load(name)`, `AgentPreset.load_all()`,
  `AgentSpec.from_preset(name)`, `list_presets()` and `AgentSpec.resolve(value)` (file,
  then preset, then inline YAML) live in `agents/factory.py`. Shipped presets: `nm2` and
  `nm3` (negamax at depth 2 and 3).

## Observability

In matches and gauntlets: the decision records above are the observability; the gauntlet
report aggregates them and flags agents with nonzero failure or overrun rates.

In the app (implemented in WP 12, see `api-and-data.md`):

- Structured JSON logs per decision (same fields as `DecisionRecord`), with request IDs.
- Prometheus metrics: `hive_decision_seconds` (histogram, by agent kind),
  `hive_decision_overrun_seconds` (histogram, by agent kind),
  `hive_decision_close_total{reason}`, `hive_worker_restarts_total`,
  `hive_worker_pool_size` / `_busy`, and `hive_illegal_submissions_total`.
- Search info is streamed to the UI live (SSE), so a person sees depth and score evolve.

Search experiments can be reproduced with `scripts/bench_search.py` (identical positions,
completed depth at fixed time) and `scripts/tune_search.py` (colour-paired seeded openings,
fixed opponents and budget). The CLI divides available CPUs by the largest participant
thread count when selecting or validating gauntlet jobs. Timing and threaded searches are
not deterministic. See `performance.md` for measured defaults and tuning evidence.

The `nm-smp` preset selects unbounded negamax with a 0.5 aspiration window, PVS and two
threads, keeping the default evaluator. The WP 28 weight sweep did not confirm a stronger
evaluator on its independent one-second test, so no tuned-weight preset is promoted.
