import { PlusIcon } from "lucide-react";
import { useId, useState, type SubmitEvent } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import type { AgentRegistration } from "@/api/client";
import { useAgentKinds, useCreateGame } from "@/api/queries";
import { PlayerSetup } from "@/components/PlayerSetup";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  agentDraft,
  describePlayer,
  HUMAN_DRAFT,
  parsePlayerDraft,
  type PlayerDraft,
} from "@/lib/players";

/** The longest game name the API accepts. */
const GAME_NAME_MAX_LENGTH = 100;

interface NewGameFormProps {
  agentKinds: AgentRegistration[];
  onCreated: (gameId: string) => void;
}

/** The new game form: a name and the setup of both sides, human vs agent by default. */
export function NewGameForm({ agentKinds, onCreated }: NewGameFormProps) {
  const nameId = useId();
  const [firstKind] = agentKinds;
  const [name, setName] = useState("");
  const [white, setWhite] = useState<PlayerDraft>(HUMAN_DRAFT);
  const [black, setBlack] = useState<PlayerDraft>(
    firstKind ? agentDraft(firstKind) : HUMAN_DRAFT,
  );
  const createGame = useCreateGame();
  const whiteResult = parsePlayerDraft(white, agentKinds);
  const blackResult = parsePlayerDraft(black, agentKinds);
  const bothHuman = white.type === "human" && black.type === "human";
  const valid = whiteResult.ok && blackResult.ok && !bothHuman;

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!whiteResult.ok || !blackResult.ok || bothHuman) {
      return;
    }

    const players = { white: whiteResult.player, black: blackResult.player };
    const gameName =
      name.trim() ||
      `${describePlayer(players.white)} vs ${describePlayer(players.black)}`;

    createGame.mutate(
      { name: gameName.slice(0, GAME_NAME_MAX_LENGTH), ...players },
      {
        onSuccess: (game) => {
          toast.success(`Created ${game.name}.`);
          onCreated(game.id);
        },
      },
    );
  };

  return (
    <form className="flex flex-col gap-6" onSubmit={submit}>
      <Field>
        <FieldLabel htmlFor={nameId}>Name</FieldLabel>
        <Input
          id={nameId}
          value={name}
          maxLength={GAME_NAME_MAX_LENGTH}
          placeholder="Named after the players"
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </Field>
      <div className="grid gap-6 sm:grid-cols-2">
        <PlayerSetup
          side="white"
          value={white}
          agentKinds={agentKinds}
          allowHuman={black.type !== "human"}
          onChange={setWhite}
        />
        <PlayerSetup
          side="black"
          value={black}
          agentKinds={agentKinds}
          allowHuman={white.type !== "human"}
          onChange={setBlack}
        />
      </div>
      <DialogFooter>
        <Button type="submit" disabled={!valid || createGame.isPending}>
          Create game
        </Button>
      </DialogFooter>
    </form>
  );
}

/** The button that opens the new game dialog, which opens the game once created. */
export function NewGameDialog() {
  const [open, setOpen] = useState(false);
  const agentKinds = useAgentKinds();
  const navigate = useNavigate();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <PlusIcon />
          New game
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New game</DialogTitle>
          <DialogDescription>
            Choose who plays each side. At least one side is an agent.
          </DialogDescription>
        </DialogHeader>
        {agentKinds.isPending && <p className="text-muted-foreground">Loading agents…</p>}
        {agentKinds.isError && (
          <p className="text-destructive">
            Could not load the agents: {agentKinds.error.message}
          </p>
        )}
        {agentKinds.isSuccess && (
          <NewGameForm
            agentKinds={agentKinds.data}
            onCreated={(gameId) => {
              setOpen(false);
              void navigate(`/games/${gameId}`);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
