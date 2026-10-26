# Frontend

A single-page app in `frontend/`, built to static files and served by FastAPI. It must work
well on a phone at the table (camera, touch) and on a desktop (agent vs agent, replay).

## Stack

| Concern | Choice |
|---|---|
| Build | Vite + React + TypeScript (strict, `noUncheckedIndexedAccess`; 5.9, see `tooling.md`) |
| Package manager | npm (lockfile committed) |
| Styling | Tailwind CSS |
| Components | shadcn/ui (Radix base, `radix-nova` style, Lucide icons), copied into `frontend/src/components/ui/` and themed; app components build on them. Add primitives with `npx shadcn@latest add <name>` |
| Server state | TanStack Query |
| Routing | React Router |
| API types | `openapi-typescript` generated from FastAPI's OpenAPI schema (`hive openapi`, no server needed) into `frontend/src/api/schema.ts` by `make api-client`; `openapi-fetch` is the thin typed client, and `unwrap` turns error bodies into an `ApiRequestError` with the API error `code`. CI fails if the generated file is stale |
| Streaming | `fetch` + a small SSE reader for `POST /think` (`EventSource` only supports GET) |
| Lint/format/test | ESLint, Prettier, Vitest + Testing Library |

Dev: `vite` dev server proxies `/api` to uvicorn. Prod: `vite build` output is copied into
the image and mounted by FastAPI.

## Structure

```
frontend/src/
├─ api/                 # schema.ts (generated), client.ts, queries.ts (TanStack hooks),
│                       # queryClient.ts (failed mutations become toasts), sse.ts
├─ lib/                 # agentParams.ts (param forms from JSON schema), players.ts, time.ts
├─ test/                # setup.ts (jsdom polyfills for Radix), fixtures, fetch mock, render
├─ components/
│  ├─ ui/               # shadcn/ui primitives: Button, Dialog, Field, Select, Sonner, ...
│  ├─ board/
│  │  ├─ types.ts       # BoardRendererProps, view models
│  │  ├─ SvgBoard.tsx   # first renderer
│  │  ├─ hex.ts         # axial ↔ pixel math (ported from hive/plotting/svg/geometry.py)
│  │  └─ useBoardInteraction.ts
│  ├─ HandTray.tsx  MoveList.tsx  PlayerSetup.tsx  AgentPicker.tsx  AgentParamInput.tsx
│  ├─ NewGameDialog.tsx  RenameGameDialog.tsx  DeleteGameDialog.tsx  GamesTable.tsx
│  ├─ ThinkingPanel.tsx  CameraCapture.tsx  MatchCandidates.tsx  ReplayControls.tsx
├─ pages/               # GamesPage.tsx, GamePage.tsx, NotFoundPage.tsx
├─ App.tsx              # router (`/`, `/games/:gameId`) and query client
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

**Games page (WP 13).** List games (name, players, status, ply, updated), paged by
`?page=N`; open, rename, export and delete from a row menu. New game dialog: choose each
side as human or agent; for agents pick kind, label, params (form generated from the param
schema) and time budget. Human vs human is not offered: the human option is disabled while
the other side is human. An empty name defaults to the players (`Human vs negamax (5 s)`),
and the new game opens once created.

The param form (`lib/agentParams.ts`) supports integers, numbers, booleans, strings and
string enums, each optionally nullable (an empty input is `null`); other schemas are edited
as JSON. Inputs hold drafts that are checked live against the schema bounds, and params left
at their default are not sent, so specs keep following the agent defaults.

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
