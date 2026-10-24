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
        self._rng = random.Random(seed)

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
- All randomness comes from `self._rng`; the seed is recorded by the runner.
- Perfect information means no `PlayerView`: agents see the full state. Agents receive
  `rules` at construction because they search.
- An agent object lives for the whole match (persistent worker), so it may keep caches
  (transposition tables, loaded models) across turns. `reset()` is optional, called
  between matches when a pooled worker is reused.

Strategies ported in WP 07:

| Kind | Params | Behaviour |
|---|---|---|
| `random` | – | Submits a random legal move with `final=True`. |
| `minimax` | `depth: int \| None`, `evaluator: EvaluatorSpec` | Iterative deepening up to `depth` (or until stopped), submitting the best move after each completed depth. |
| `negamax` | same as minimax | Same, negamax formulation. |

Evaluators (`material`, `mobility`, `positioning`, `queen_safety`, weighted composite) stay
as they are; they are configured through `EvaluatorSpec` (kind, params, weights).

### Factory (WP 07)

```python
@dataclass(frozen=True, slots=True)
class AgentSpec:
    kind: str
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    label: str | None = None   # display name in reports and UI

def build_agent(spec: AgentSpec, rules: Rules, *, seed: int) -> Agent: ...
def agent_kinds() -> list[AgentKindInfo]: ...   # name, description, param schema
```

- A registry maps kind names to classes and a parameter schema (a small pydantic model per
  kind is fine), so the API can list agents and render parameter forms, and the CLI can
  parse `negamax:depth=4,evaluator=default`.
- Params are free-form JSON, so a future neural agent can take `weights: "s3://..."` or
  `hidden_size: 256` without interface changes.

## Persistent workers and the runner (WP 08)

Modelled on how UCI chess engines and tournament managers (cutechess-cli) work: one
long-lived engine process per side, cooperative time management, and kills only for
misbehaviour.

```
parent (runner)                                   worker process (one per seat)
────────────────                                  ───────────────────────────────
start worker(spec, rules, seed)  ───────────────▶ build_agent once (models load here)
per turn:                                          loop:
  send Think(state, deadline)    ───────────────▶   receive Think
                                                     clear stop event
                                                     agent.think(state, PipeTurnContext)
  receive Submission/Info        ◀───────────────     submit / info → pipe
  at deadline: set stop event,                       return → send Idle
  take latest legal candidate
  wait ≤ grace for Idle          ◀───────────────
  if no Idle: kill + restart, record failure
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

### Decision records

Every decision produces a `DecisionRecord`:

| Field | Meaning |
|---|---|
| `ply`, `player`, `agent_label`, `seed` | who decided what, reproducibly |
| `budget_s`, `elapsed_s`, `overrun_s` | time accounting (`overrun_s` = time past deadline until Idle) |
| `close_reason` | `final`, `deadline`, `worker_failed`, `no_candidate` |
| `candidates`, `illegal_submissions` | counts |
| `move` | the applied move (serialized) |
| `last_info` | the last `info` payload (depth, nodes, score, pv) |
| `worker_restarted`, `failure` | safety-net events with a truncated message |

A `MatchResult` holds the rules, both specs, the game record (serialized), decision records, the
result (winner, draw, turn cap) and timing totals.

## Gauntlets (WP 09)

`hive gauntlet` runs scheduled matches between participants and writes a report:

```
hive gauntlet \
  --agent "negamax:depth=3,label=nm3" \
  --agent "minimax:depth=3,label=mm3" \
  --agent "random" \
  --games-per-pair 20 --budget 2.0 --max-turns 100 \
  --seed 42 --jobs 4 --out reports/gauntlet-2026-10-24.json [--replays]
```

- Schedule: round robin, each pairing played with both colours equally often.
- Seeds: derived deterministically from the experiment seed per match and seat (as in
  `shed.gauntlet.derive_seed`), so any match can be reproduced.
- Fairness: concurrent matches are capped at `cpu_count // 2` by default (two timed workers
  per match), and the CLI refuses higher `--jobs` unless `--allow-oversubscribe` is given.
- Output: a versioned JSON document with config, per-participant results (wins, draws,
  losses, win rate with confidence interval, Elo estimate), per-participant decision stats
  (depth reached distribution, nodes/s, timeout rate, overrun distribution, failures,
  illegal submissions), and optionally full replays of every match.
- A short human-readable summary table is logged at the end.
- `hive replay <report> --match N` prints or plots a recorded match using the existing
  plotting helpers.

## Observability

In matches and gauntlets: the decision records above are the observability; the gauntlet
report aggregates them and flags agents with nonzero failure or overrun rates.

In the app (implemented in WP 12, see `api-and-data.md`):

- Structured JSON logs per decision (same fields as `DecisionRecord`), with request IDs.
- Prometheus metrics: `hive_decision_seconds` (histogram, by agent kind),
  `hive_decision_overrun_seconds`, `hive_decision_close_total{reason}`,
  `hive_worker_restarts_total`, `hive_worker_pool_size` / `_busy`, and
  `hive_illegal_submissions_total`.
- Search info is streamed to the UI live (SSE), so a person sees depth and score evolve.
