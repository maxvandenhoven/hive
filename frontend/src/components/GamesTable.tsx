import { DownloadIcon, EllipsisVerticalIcon, PencilIcon, TrashIcon } from "lucide-react";
import { Link } from "react-router";

import { gameExportUrl, type GameSummary } from "@/api/client";
import { GameStatusBadge } from "@/components/GameStatusBadge";
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
import { describePlayer } from "@/lib/players";
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

interface GamesTableProps {
  games: GameSummary[];
  onRename: (game: GameSummary) => void;
  onDelete: (game: GameSummary) => void;
}

/** The games with their players, status, ply and last change; names open the game. */
export function GamesTable({ games, onRename, onDelete }: GamesTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead className="hidden sm:table-cell">Players</TableHead>
          <TableHead>Status</TableHead>
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
            <TableCell className="max-w-48 truncate font-medium">
              <Link to={`/games/${game.id}`} className="hover:underline">
                {game.name}
              </Link>
            </TableCell>
            <TableCell className="hidden text-muted-foreground sm:table-cell">
              {describePlayer(game.white)} vs {describePlayer(game.black)}
            </TableCell>
            <TableCell>
              <GameStatusBadge game={game} />
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
