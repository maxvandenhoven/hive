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
│                       # moves.ts (move descriptions, side at a ply, board view models),
│                       # search.ts (search info summaries and formatting)
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
│  ├─ useAgentTurns.ts  ThinkingPanel.tsx  MatchControls.tsx  ReplayControls.tsx
│  ├─ PlayerSetup.tsx  AgentPicker.tsx  AgentParamInput.tsx  GameStatusBadge.tsx
│  ├─ NewGameDialog.tsx  RenameGameDialog.tsx  DeleteGameDialog.tsx  GamesTable.tsx
│  ├─ CameraCapture.tsx  MatchCandidates.tsx
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
  proposedMove: MoveView | null; // an agent's best move, or the move to make on the board
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
409 is shown as a toast and the game is refetched. A move, undo or committed agent
decision stores the returned position as the latest, drops cached targets and stored
positions from that ply on, and refreshes the game and the game list. In a human vs agent
game, undo takes back to the person's last turn (two moves when the agent answered), so
the agent does not replay its answer at once; several plies are undone in one mutation.
A game over banner shows the result (undo reopens the game); abandoned games are
read-only.

Query notes: positions (`["games", "detail", id, "position", ply | "latest"]`) and targets
live under the game's key, so refreshing a game refreshes them. Queries whose `meta` sets
`toastErrors` report failures in a toast like mutations (used for targets, which follow a
click). openapi-fetch reads tuples such as `Coordinate` as plain arrays, so responses with
coordinates are cast to their schema types in `queries.ts`.

**Game page, agent turn (WP 15).** `useAgentTurns` starts `POST /think` with
`commit=true` whenever an agent is to move in an active game and no other write is under
way. `api/sse.ts` reads the stream from `fetch` (`EventSource` only supports GET):
`ServerSentEventParser` turns chunks into event data, `streamThinkEvents` yields the typed
events and throws an `ApiRequestError` for an error response. The `ThinkingPanel` shows
the time left of the side's budget (counted from when the stream opened), depth, score
(`Win in 3 plies` for forced results), nodes and nodes/s, and the best move so far, which
the board draws as `proposedMove` (an arrow from its source and a ring on its target).
When the decision arrives with its position, the move is stored and, in a human vs agent
game, the panel asks to "Make this move on the board" with a **Done** button (from WP 19,
alternatively the camera to verify); the board keeps pointing at the move and the person
cannot play until Done. A failed request or an `error` event (for example `ply_conflict`)
is shown as a toast and in the panel with **Try again**, and the game is refetched. The
stream is aborted, which stops the agent without committing, when the page closes,
another write starts (undo while the agent thinks) or a match pauses. The Done prompt
lives in the page only, so reloading skips it.

**Agent vs agent (WP 15).** `MatchControls`: **Play**/**Pause**, **Step** (one move while
paused) and a delay between moves (none, 1, 2 or 5 s, default 1 s). The page drives the
loop by calling `think` with `commit=true` for whichever side is to move. Matches do not
wait for Done, since they are watched on the screen; Step plays one move at a time for
following on a physical board. A match starts paused, and undo pauses it.

**Replay (WP 15).** `ReplayControls` (first, previous, next, live and a slider) and the
move list (a move shows the position after it) set the ply shown, loaded with
`GET /state?ply=N`; the position shown before stays while the next one loads. The last ply
is the live position, which follows new moves; a replayed ply past the last move (after
an undo) shows the live one. Replayed positions are read-only and marked on the board,
while agent turns carry on in the live game.

**Camera (WP 16, WP 19).** A camera button on human turns opens `CameraCapture`
(`<input type="file" accept="image/*" capture="environment">` first; a `getUserMedia`
viewfinder with a framing overlay later). WP 16 uploads and stores the photo. WP 19 shows
the proposed move for confirmation, or `MatchCandidates` (top candidates plus manual entry)
when the match is weak. On agent turns, the photo verifies that the expected move was
made. Camera access needs HTTPS, which the Tailscale ingress provides in production; in
local dev use `localhost`.
