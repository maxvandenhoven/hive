import { useState } from "react";
import { useSearchParams } from "react-router";

import type { GameSummary } from "@/api/client";
import { useGamePage } from "@/api/queries";
import { DeleteGameDialog } from "@/components/DeleteGameDialog";
import { GamesTable } from "@/components/GamesTable";
import { NewGameDialog } from "@/components/NewGameDialog";
import { RenameGameDialog } from "@/components/RenameGameDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

/** The number of games on one page of the list. */
export const GAMES_PAGE_SIZE = 20;

function readPageNumber(value: string | null): number {
  const page = Number(value);

  return Number.isInteger(page) && page > 1 ? page : 1;
}

/** The game list, newest first, with the new game dialog and the game actions. */
export function GamesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const pageNumber = readPageNumber(searchParams.get("page"));
  const offset = (pageNumber - 1) * GAMES_PAGE_SIZE;
  const gamePage = useGamePage(GAMES_PAGE_SIZE, offset);
  const [renaming, setRenaming] = useState<GameSummary | null>(null);
  const [deleting, setDeleting] = useState<GameSummary | null>(null);

  const goToPage = (page: number) => {
    setSearchParams(page > 1 ? { page: String(page) } : {});
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-heading text-2xl font-semibold">Games</h1>
        <NewGameDialog />
      </div>
      <Card className="py-0">
        <CardContent className="px-0">
          {gamePage.isPending && (
            <p className="p-6 text-muted-foreground">Loading games…</p>
          )}
          {gamePage.isError && (
            <p className="p-6 text-destructive">
              Could not load the games: {gamePage.error.message}
            </p>
          )}
          {gamePage.isSuccess && gamePage.data.items.length === 0 && (
            <p className="p-6 text-muted-foreground">
              {gamePage.data.total === 0
                ? "No games yet. Start one with New game."
                : "No games on this page."}
            </p>
          )}
          {gamePage.isSuccess && gamePage.data.items.length > 0 && (
            <GamesTable
              games={gamePage.data.items}
              onRename={setRenaming}
              onDelete={setDeleting}
            />
          )}
        </CardContent>
      </Card>
      {gamePage.isSuccess && gamePage.data.total > GAMES_PAGE_SIZE && (
        <div className="flex items-center justify-between gap-4 text-sm text-muted-foreground">
          <span>
            {offset + 1}–{offset + gamePage.data.items.length} of {gamePage.data.total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={pageNumber === 1}
              onClick={() => {
                goToPage(pageNumber - 1);
              }}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              disabled={offset + GAMES_PAGE_SIZE >= gamePage.data.total}
              onClick={() => {
                goToPage(pageNumber + 1);
              }}
            >
              Next
            </Button>
          </div>
        </div>
      )}
      <RenameGameDialog
        game={renaming}
        onClose={() => {
          setRenaming(null);
        }}
      />
      <DeleteGameDialog
        game={deleting}
        onClose={() => {
          setDeleting(null);
        }}
      />
    </div>
  );
}
