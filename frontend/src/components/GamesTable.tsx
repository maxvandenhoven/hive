import { DownloadIcon, EllipsisVerticalIcon, PencilIcon, TrashIcon } from "lucide-react";
import { Link } from "react-router";

import { gameExportUrl, type GameSummary } from "@/api/client";
import { GAME_SCENARIO_ICONS } from "@/components/scenarioIcons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  describeGameScenario,
  describeNextAction,
  describePlayer,
  gameScenario,
} from "@/lib/players";
import { formatRelativeTime } from "@/lib/time";

interface GameActionsProps {
  game: GameSummary;
  onRename: (game: GameSummary) => void;
  onDelete: (game: GameSummary) => void;
}

function GameActions({ game, onRename, onDelete }: GameActionsProps) {
  return (
    // Not modal, so the dialogs it opens get the focus and pointer events back.
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${game.name}`}>
          <EllipsisVerticalIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onSelect={() => {
            onRename(game);
          }}
        >
          <PencilIcon />
          Rename
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <a href={gameExportUrl(game.id)} download>
            <DownloadIcon />
            Export
          </a>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          variant="destructive"
          onSelect={() => {
            onDelete(game);
          }}
        >
          <TrashIcon />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The scenario of a game as an icon and a short label, such as `hints game`. */
function GameScenarioLabel({ game }: { game: GameSummary }) {
  const Icon = GAME_SCENARIO_ICONS[gameScenario(game)];

  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {describeGameScenario(game)}
    </span>
  );
}

/**
 * What happens next in a game: honey when it waits for a person, such as `Your turn`,
 * secondary for an agent's turn or a result, outline once abandoned.
 */
function GameNextActionBadge({ game }: { game: GameSummary }) {
  const action = describeNextAction(game);
  let variant: "default" | "secondary" | "outline" = "secondary";

  if (game.status === "abandoned") {
    variant = "outline";
  } else if (action.waitsForPerson) {
    variant = "default";
  }

  return <Badge variant={variant}>{action.label}</Badge>;
}

interface GamesTableProps {
  games: GameSummary[];
  onRename: (game: GameSummary) => void;
  onDelete: (game: GameSummary) => void;
}

/**
 * The games with their scenario, next action, players, ply and last change; names open
 * the game.
 */
export function GamesTable({ games, onRename, onDelete }: GamesTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Next</TableHead>
          <TableHead className="hidden lg:table-cell">Players</TableHead>
          <TableHead className="text-right">Ply</TableHead>
          <TableHead className="hidden md:table-cell">Updated</TableHead>
          <TableHead className="w-0">
            <span className="sr-only">Actions</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {games.map((game) => (
          <TableRow key={game.id}>
            <TableCell className="max-w-48 sm:max-w-72">
              <div className="flex flex-col gap-0.5">
                <Link
                  to={`/games/${game.id}`}
                  className="truncate font-medium hover:underline"
                >
                  {game.name}
                </Link>
                <GameScenarioLabel game={game} />
              </div>
            </TableCell>
            <TableCell>
              <GameNextActionBadge game={game} />
            </TableCell>
            <TableCell className="hidden text-muted-foreground lg:table-cell">
              {describePlayer(game.white)} vs {describePlayer(game.black)}
            </TableCell>
            <TableCell className="text-right tabular-nums">{game.ply_count}</TableCell>
            <TableCell className="hidden text-muted-foreground md:table-cell">
              <time
                dateTime={game.updated_at}
                title={new Date(game.updated_at).toLocaleString()}
              >
                {formatRelativeTime(game.updated_at)}
              </time>
            </TableCell>
            <TableCell>
              <GameActions game={game} onRename={onRename} onDelete={onDelete} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
