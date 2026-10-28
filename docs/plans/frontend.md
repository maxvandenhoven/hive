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
│  │  ├─ boardMarks.ts  # mark kinds, legend labels, which marks props show
│  │  ├─ marks.tsx      # the mark components and legend swatches
│  │  ├─ BoardLegend.tsx # the Key button and legend, shared by renderers and help
│  │  ├─ grid.ts        # the background hex grid cells in view
│  │  ├─ colors.ts      # raw values of the board colour tokens, for non-CSS renderers
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
  movable: HexCoord[];           // tiles that may move (ringed and raised)
  selected: HexCoord | null;
  lastMove: MoveView | null;     // from (null for a placement) and to
  proposedMove: MoveView | null; // an agent's best move, or the move to make on the board
  forbidden?: HexCoord[];        // "not allowed" hexes for the rule diagrams; games omit it
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

`SvgBoard` draws a background hex grid (`--board-grid` on `--board-surface`), then tiles
(owner colours, the insect graphic, the pieces below the top one peeking out, a stack
height badge) and the marks, all in the board colours of [Theme](#theme). The grid is one
path of the hexes that overlap the visible part of the board (`gridCells` in `grid.ts`),
recomputed from the `viewBox` and the SVG's measured size (`visibleViewBox`, since a
`meet` viewBox shows more along the longer side), with a non-scaling 1.25 px stroke so it
reads at every zoom level.

**Marks.** One mark per meaning (`marks.tsx`, kinds in `boardMarks.ts`), each also told
apart by shape, dash or fill so it reads without colour:

| Mark | Prop | Drawing |
|---|---|---|
| Can move | `movable` | Solid ring on the tile, which is raised by a shadow (`--board-movable`) |
| Selected | `selected` | Solid wide halo behind the tile (`--board-movable`) |
| Can go here | `highlights`, empty hex | Dashed hex with a dot (`--board-target`) |
| Can climb on top | `highlights`, occupied hex | Dashed ring with a dot on the tile (`--board-target`) |
| Last move | `lastMove` | Dotted outline with a light fill on from, stronger on to (`--board-last-move`) |
| Agent suggestion | `proposedMove` | Arrow to a double ring (`--board-suggestion`) |
| Not allowed | `forbidden` | Hex with a cross (`--board-forbidden`), for the rule diagrams of WP 38 |

The hand trays use the same components: a placeable piece is raised with a ring, the
selected one has the halo.

**Legend.** `BoardLegend` is a Key button with a small panel that lists the marks on the
board now first (`boardMarksShown(props)`), then the rest, each with a swatch drawn by
`MarkSwatch` from the mark components themselves, so they always match. Whether it is
open is remembered per device (`localStorage`). A renderer places it on the board (the 2D
board at the bottom left); the 2.5D board (WP 39) and the help (WP 37) reuse it and
`MarkSwatch`. On a phone the panel leaves out the one-line descriptions.

Interactive parts are SVG elements with `role="button"` and keyboard activation. The view
is the SVG `viewBox` in board units, so fitting needs no measuring: it fits the stacks plus every neighbouring hex (where all
targets lie, so the view stays steady while selecting), with a minimum size. Dragging pans
(after a 6 px threshold, so taps stay clicks), two pointers pinch to zoom, the mouse wheel
and the buttons zoom; the view then stays put until the fit button. The SVG has
`touch-action: none`, so the page does not scroll or zoom while panning the board.

The insect graphics are imported from `src/hive/assets/svg/` through the `@insects` Vite
alias (`server.fs.allow` admits the folder in dev), so the Python plots and the app share
one copy. The frontend build therefore needs that folder next to `frontend/`, including in
the Docker build stage (WP 25).

## Theme

One theme, "Slate & Honey" (D28): cool slate neutrals, a dark slate header and one honey
accent. No dark mode and no theme switch, so `ui/` has no `dark:` classes and there is no
`next-themes`. It should feel calm and a bit premium: no illustrations, no bouncy UI.

The tokens live in `frontend/src/index.css` as CSS variables, exposed as Tailwind colours
(`bg-card`, `ring-board-movable`, `fill-tile-white`). App components style only through
these tokens and the `ui/` variants, never with one-off colours. Values were adjusted from
the mockup where WCAG AA needed it (marked *).

| Token | Value | Use |
|---|---|---|
| `--background` | `#e8ecf0` | Page |
| `--foreground` | `#1c2530` | Text (13:1 on the page) |
| `--muted-foreground` | `#536070`* | Secondary text (≥ 4.5:1 on page, card and secondary) |
| `--card`, `--popover` | `#f7f9fb` | Cards (`--border` ring and a faint shadow), popovers |
| `--border` | `#d3dae1` | Card and table borders |
| `--input` | `#7b8896`* | Input, select and checkbox borders (3:1 on the page) |
| `--secondary`, `--muted`, `--accent` | `#dfe5eb` | Secondary buttons, finished badges, hovers |
| `--primary` / `--primary-foreground` | `#e0a526` / `#1c2530` | Primary buttons, active and "your turn" badges, the hand of the side to move |
| `--ring` | `#a8740c`* | Focus rings: a deeper honey, ≥ 3:1 on page and card |
| `--destructive` | `#b42828`* | Errors and delete actions (5:1 on the page) |
| `--header` / `--header-foreground` | `#1c2530` / `#f3f5f7` | App header with the honey hexagon logo |

Honey is for fills, never for text on light surfaces (2:1). Links are foreground text with
a honey underline. Status badges: active is primary (honey), finished secondary, abandoned
outline.

**Board colours.** Each board colour has one meaning, shared by the 2D board, the 2.5D
board (WP 39), the legend (WP 32) and the help. CSS can use the classes; renderers that
cannot (Three.js) read the same values from `components/board/colors.ts`, which a test
keeps equal to `index.css`. The Python plots keep their own colours.

| Token | Value | Meaning |
|---|---|---|
| `--board-surface` | `#d5dde5` | The board background (the board card) |
| `--board-grid` | `rgb(28 37 48 / 16%)` | The background hex grid (WP 32) |
| `--tile-white` / `--tile-black` / `--tile-stroke` | `#f6f1e6` / `#2a2f36` / `#4a5562` | Tiles of each side and their outline |
| `--board-movable` | `#2b7fd6` | Tiles that can move, and the selection (also the selected hand piece) |
| `--board-target` | `#2f9e6b` | Where the selection can go; "allowed" in rule diagrams |
| `--board-forbidden` | `#d64545` | "Not allowed" in rule diagrams |
| `--board-last-move` | `#e0a526` | The last move |
| `--board-suggestion` | `#8b5cf6` | A move suggested by an agent: its best move while thinking, the move to make on the table, a hint |

The stack height badge is neutral (card fill, foreground text), since a stack has no
board meaning of its own.

**Frame.** The header and the page share one frame: up to 96 rem wide on a desktop, one
column with 16 px gutters on a phone. The right of the header is kept for actions (Help
arrives in WP 37).

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
