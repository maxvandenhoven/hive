import { toast } from "sonner";

import type { GameSummary } from "@/api/client";
import { useDeleteGame } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface DeleteGameDialogProps {
  /** The game to delete; the dialog is open while it is set. */
  game: GameSummary | null;
  onClose: () => void;
}

export function DeleteGameDialog({ game, onClose }: DeleteGameDialogProps) {
  const deleteGame = useDeleteGame();

  const confirm = () => {
    if (game === null) {
      return;
    }

    deleteGame.mutate(game.id, {
      onSuccess: () => {
        toast.success(`Deleted ${game.name}.`);
        onClose();
      },
    });
  };

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
          <DialogTitle>Delete game?</DialogTitle>
          <DialogDescription>
            {game?.name} is deleted with its moves and photos. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button variant="destructive" disabled={deleteGame.isPending} onClick={confirm}>
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
