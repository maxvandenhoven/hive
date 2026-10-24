# Frontend

A single-page app in `frontend/`, built to static files and served by FastAPI. It must work
well on a phone at the table (camera, touch) and on a desktop (agent vs agent, replay).

## Stack

| Concern | Choice |
|---|---|
| Build | Vite + React + TypeScript (strict) |
| Package manager | npm (lockfile committed) |
| Styling | Tailwind CSS |
| Components | shadcn/ui, copied into `frontend/src/components/ui/` and themed; app components build on them |
| Server state | TanStack Query |
| Routing | React Router |
| API types | `openapi-typescript` generated from FastAPI's OpenAPI schema into `frontend/src/api/schema.ts`, with a thin typed fetch wrapper; CI fails if the generated file is stale |
| Streaming | `fetch` + a small SSE reader for `POST /think` (`EventSource` only supports GET) |
| Lint/format/test | ESLint, Prettier, Vitest + Testing Library |

Dev: `vite` dev server proxies `/api` to uvicorn. Prod: `vite build` output is copied into
the image and mounted by FastAPI.

## Structure

```
frontend/src/
├─ api/                 # schema.ts (generated), client.ts, queries.ts (TanStack hooks), sse.ts
├─ components/
│  ├─ ui/               # shadcn/ui primitives: Button, Dialog, Sheet, Toast, Select, ...
│  ├─ board/
│  │  ├─ types.ts       # BoardRendererProps, view models
│  │  ├─ SvgBoard.tsx   # first renderer
│  │  ├─ hex.ts         # axial ↔ pixel math (ported from hive/plotting/svg/geometry.py)
│  │  └─ useBoardInteraction.ts
│  ├─ HandTray.tsx  MoveList.tsx  PlayerSetup.tsx  AgentPicker.tsx
│  ├─ ThinkingPanel.tsx  CameraCapture.tsx  MatchCandidates.tsx  ReplayControls.tsx
├─ pages/               # GamesPage.tsx, GamePage.tsx, NewGameDialog
└─ main.tsx
```

Rule: pages compose app components; app components compose `ui/` primitives; nothing
outside `ui/` styles raw HTML buttons or dialogs directly. This keeps styling consistent and
maintenance in one place.

## Board rendering

Board logic is separate from drawing, so renderers are swappable (SVG now, a React Three
Fiber `ThreeBoard` later behind a settings toggle):

```ts
interface BoardRendererProps {
  board: BoardView;              // stacks per hex, top piece first
  highlights: HexCoord[];        // legal targets of the selected tile
  movable: HexCoord[];           // tiles that may move (outlined)
  selected: HexCoord | null;
  lastMove: MoveView | null;
  onHexClick: (coord: HexCoord) => void;
}
```

`useBoardInteraction` owns selection state and maps clicks to intents: select a movable
tile → fetch targets → click a target → play move. For placements, selecting a piece in the
`HandTray` highlights `placeable_coords`. Insect graphics reuse the SVG assets from
`src/hive/assets/svg/` (copied into `frontend/public/` at build time or imported).

Stacks show the top piece with a stack height badge; tapping a stack lists its contents.

## Flows

**Games page (WP 13).** List games (name, players, status, ply, updated), create, rename,
delete, open. New game dialog: choose each side as human or agent; for agents pick kind,
params (form generated from the param schema) and time budget. Human vs human is not
offered.

**Game page, human turn (WP 14).** Board + hand trays + move list. Manual entry by tapping.
Undo last move. Game over banner.

**Game page, agent turn (WP 15).** The page calls `POST /think` with `commit=true`; the
`ThinkingPanel` shows depth, score, nodes/s and the current best move live. Once committed,
the move is highlighted on the board with a "Make this move on the board" prompt and a
**Done** button (from WP 19, alternatively the camera to verify).

**Agent vs agent (WP 15).** Play/pause toggle and step button; the frontend drives the
loop by calling `think` with `commit=true` for whichever side is to move. Optional delay
between moves.

**Replay (WP 15).** `ReplayControls` scrub through plies using `GET /state?ply=N`; works for
finished and active games.

**Camera (WP 16, WP 19).** A camera button on human turns opens `CameraCapture`
(`<input type="file" accept="image/*" capture="environment">` first; a `getUserMedia`
viewfinder with a framing overlay later). WP 16 uploads and stores the photo. WP 19 shows
the proposed move for confirmation, or `MatchCandidates` (top candidates plus manual entry)
when the match is weak. On agent turns, the photo verifies that the expected move was
made. Camera access needs HTTPS, which the Tailscale ingress provides in production; in
local dev use `localhost`.
