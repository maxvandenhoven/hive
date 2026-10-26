import { useId, useState, type SubmitEvent } from "react";
import { toast } from "sonner";

import type { GameSummary } from "@/api/client";
import { useUpdateGame } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";

interface RenameGameFormProps {
  game: GameSummary;
  onDone: () => void;
}

function RenameGameForm({ game, onDone }: RenameGameFormProps) {
  const nameId = useId();
  const [name, setName] = useState(game.name);
  const updateGame = useUpdateGame();
  const trimmed = name.trim();

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateGame.mutate(
      { gameId: game.id, body: { name: trimmed } },
      {
        onSuccess: (updated) => {
          toast.success(`Renamed to ${updated.name}.`);
          onDone();
        },
      },
    );
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={submit}>
      <Field>
        <FieldLabel htmlFor={nameId}>Name</FieldLabel>
        <Input
          id={nameId}
          value={name}
          maxLength={100}
          autoFocus
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </Field>
      <DialogFooter>
        <Button type="submit" disabled={trimmed === "" || updateGame.isPending}>
          Rename
        </Button>
      </DialogFooter>
    </form>
  );
}

interface RenameGameDialogProps {
  /** The game to rename; the dialog is open while it is set. */
  game: GameSummary | null;
  onClose: () => void;
}

export function RenameGameDialog({ game, onClose }: RenameGameDialogProps) {
  return (
    <Dialog
      open={game !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename game</DialogTitle>
        </DialogHeader>
        {game && <RenameGameForm game={game} onDone={onClose} />}
      </DialogContent>
    </Dialog>
  );
}
