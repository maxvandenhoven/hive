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
├─ lib/                 # agentParams.ts (param forms from JSON schema), players.ts, time.ts,
│                       # moves.ts (move descriptions, side at a ply, board view models)
├─ test/                # setup.ts (jsdom polyfills for Radix), fixtures, fetch mock, render
├─ components/
│  ├─ ui/               # shadcn/ui primitives: Button, Dialog, Field, Popover, Sonner, ...
│  ├─ board/
│  │  ├─ types.ts       # BoardRendererProps, view models
│  │  ├─ SvgBoard.tsx   # first renderer
│  │  ├─ PieceTile.tsx  # a piece as a tile (board) or icon (trays, lists); insects.ts
│  │  ├─ hex.ts         # axial ↔ pixel math (ported from hive/plotting/svg/geometry.py)
│  │  ├─ viewBox.ts     # fitting, panning and zooming the SVG viewBox
│  │  ├─ useViewGestures.ts     # drag to pan, pinch and wheel to zoom
│  │  └─ useBoardInteraction.ts # selection → targets → move
│  ├─ HandTray.tsx  MoveList.tsx  GameHeader.tsx  GameOverBanner.tsx
│  ├─ PlayerSetup.tsx  AgentPicker.tsx  AgentParamInput.tsx  GameStatusBadge.tsx
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
Fiber `ThreeBoard` later behind a settings toggle). Pages use a renderer only through its
props (`const Board: BoardRenderer = SvgBoard`):

```ts
interface BoardRendererProps {
  board: BoardView;              // stacks per hex, top piece first
  highlights: HexCoord[];        // where a click plays a move: targets or placements
  movable: HexCoord[];           // tiles that may move (outlined)
  selected: HexCoord | null;
  lastMove: MoveView | null;     // from (null for a placement) and to
  onHexClick: (coord: HexCoord) => void;
}
```

Renderers know nothing about the game: every hex reports clicks, also empty ones, and the
interaction code decides what a click means. Showing the contents of a stack is part of
drawing, so the renderer owns it: tapping a stack of two or more pieces that is not a
highlight opens a popover listing its pieces from the top; tapping it again, or anywhere
else, closes it.

`useBoardInteraction` owns the selection and maps clicks to intents (`resolveHexClick`,
`resolveHandClick`, pure and tested on their own): select a movable tile → fetch its
targets (`GET /targets`) → click a target → play the move. Selecting a piece type in the
`HandTray` highlights `placeable_coords` instead. Clicking the selection again, or a hex
that is neither movable nor highlighted, clears it. A highlight wins over a movable tile
on the same hex (a beetle climbing onto it). Moves are only built from the API's targets
and placements, so only legal moves are sent. The selection belongs to a ply and is
dropped when the position changes or the board is disabled (agent turn, game over, a move
being sent).

`SvgBoard` draws tiles (owner colours as in the Python plots, the insect graphic, the
pieces below the top one peeking out, a stack height badge), movable outlines, the
selected tile, the targets (dashed hexes with a dot, or a ring on an occupied hex) and the
last move (amber halos on its from and to hexes). Interactive parts are SVG elements with
`role="button"` and keyboard activation. The view is the SVG `viewBox` in board units, so
fitting needs no measuring: it fits the stacks plus every neighbouring hex (where all
targets lie, so the view stays steady while selecting), with a minimum size. Dragging pans
(after a 6 px threshold, so taps stay clicks), two pointers pinch to zoom, the mouse wheel
and the buttons zoom; the view then stays put until the fit button. The SVG has
`touch-action: none`, so the page does not scroll or zoom while panning the board.

The insect graphics are imported from `src/hive/assets/svg/` through the `@insects` Vite
alias (`server.fs.allow` admits the folder in dev), so the Python plots and the app share
one copy. The frontend build therefore needs that folder next to `frontend/`, including in
the Docker build stage (WP 25).

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

**Game page, human turn (WP 14).** Header (name, status, players, whose turn and the
ply), the board between the two hand trays (the side a person plays below), undo, export
and the move list. On a phone the parts stack in one column with a square board; on a
desktop the header, actions and moves sit in a side panel. Manual entry by tapping as
described under "Board rendering"; a **Pass** button appears when the API reports
`must_pass`. Moves are sent with `expected_ply` set to the `ply_count` of the position
shown and undo with `?expected_ply=`, so a stale page cannot overwrite a newer game: the
409 is shown as a toast and the game is refetched. A move or undo stores the returned
position as the latest, drops cached targets and refreshes the game and the game list.
Agent sides are read-only (their turns come with WP 15). A game over banner shows the
result (undo reopens the game); abandoned games are read-only.

Query notes: positions (`["games", "detail", id, "position", ply | "latest"]`) and targets
live under the game's key, so refreshing a game refreshes them. Queries whose `meta` sets
`toastErrors` report failures in a toast like mutations (used for targets, which follow a
click). openapi-fetch reads tuples such as `Coordinate` as plain arrays, so responses with
coordinates are cast to their schema types in `queries.ts`.

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
