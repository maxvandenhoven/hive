import { ChevronLeftIcon, PlusIcon } from "lucide-react";
import { useId, useState, type ReactNode, type SubmitEvent } from "react";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { useAgentKinds, useAgentPresets, useCreateGame } from "@/api/queries";
import { AgentChoiceField } from "@/components/AgentChoiceField";
import { ChoiceCards } from "@/components/ChoiceCards";
import { GAME_SCENARIO_ICONS } from "@/components/scenarioIcons";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
  FieldTitle,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  buildNewGameRequest,
  defaultGameName,
  OPPONENT_DEFAULT_NAME,
  PLAYER_NAME_MAX_LENGTH,
  defaultNewGameChoices,
  GAME_NAME_MAX_LENGTH,
  readNewGameChoices,
  writeNewGameChoices,
  type AgentGameChoices,
  type HintsGameChoices,
  type NewGameAgents,
  type NewGameChoices,
  type WatchGameChoices,
} from "@/lib/newGame";
import { GAME_SCENARIO_INFO, GAME_SCENARIOS, type GameScenario } from "@/lib/players";

interface ScenarioCardsProps {
  value: GameScenario | null;
  onChoose: (scenario: GameScenario) => void;
}

/** Step 1: three large cards, one per scenario. */
function ScenarioCards({ value, onChoose }: ScenarioCardsProps) {
  return (
    <div className="flex flex-col gap-3">
      {GAME_SCENARIOS.map((scenario) => {
        const Icon = GAME_SCENARIO_ICONS[scenario];
        const info = GAME_SCENARIO_INFO[scenario];

        return (
          <Button
            key={scenario}
            type="button"
            variant="outline"
            aria-pressed={value === scenario}
            className="h-auto justify-start gap-4 p-4 text-left whitespace-normal aria-pressed:border-primary"
            onClick={() => {
              onChoose(scenario);
            }}
          >
            <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Icon className="size-6" />
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-base font-semibold">{info.title}</span>
              <span className="font-normal text-muted-foreground">
                {info.description}
              </span>
            </span>
          </Button>
        );
      })}
    </div>
  );
}

interface ScenarioSetupProps<Choices> {
  value: Choices;
  agents: NewGameAgents;
  onChange: (choices: Choices) => void;
}

function AgentGameSetup({
  value,
  agents,
  onChange,
}: ScenarioSetupProps<AgentGameChoices>) {
  const hintsId = useId();

  return (
    <>
      <ChoiceCards
        legend="Your colour"
        layout="row"
        value={value.colour}
        options={[
          { value: "white", title: "White" },
          { value: "black", title: "Black" },
          { value: "random", title: "Random" },
        ]}
        onChange={(colour) => {
          onChange({ ...value, colour });
        }}
      />
      <AgentChoiceField
        label="Opponent"
        value={value.opponent}
        agents={agents}
        onChange={(opponent) => {
          onChange({ ...value, opponent });
        }}
      />
      <FieldLabel htmlFor={hintsId}>
        <Field orientation="horizontal" className="min-h-11">
          <Checkbox
            id={hintsId}
            checked={value.hints}
            onCheckedChange={(checked) => {
              onChange({ ...value, hints: checked === true });
            }}
          />
          <FieldContent>
            <FieldTitle>Hints for you</FieldTitle>
            <FieldDescription>An agent suggests a move on your turns.</FieldDescription>
          </FieldContent>
        </Field>
      </FieldLabel>
      {value.hints && (
        <AgentChoiceField
          label="Hint strength"
          value={value.hint}
          agents={agents}
          onChange={(hint) => {
            onChange({ ...value, hint });
          }}
        />
      )}
    </>
  );
}

function HintsGameSetup({
  value,
  agents,
  onChange,
}: ScenarioSetupProps<HintsGameChoices>) {
  const opponentId = useId();

  return (
    <>
      <p className="text-muted-foreground">
        Always at the table: play on a physical board and enter each move here. Only you
        get hints.
      </p>
      <ChoiceCards
        legend="Your colour"
        layout="row"
        value={value.colour}
        options={[
          { value: "white", title: "White" },
          { value: "black", title: "Black" },
          { value: "random", title: "Random" },
        ]}
        onChange={(colour) => {
          onChange({ ...value, colour });
        }}
      />
      <Field>
        <FieldLabel htmlFor={opponentId}>Opponent's name</FieldLabel>
        <Input
          id={opponentId}
          value={value.opponentName}
          maxLength={PLAYER_NAME_MAX_LENGTH}
          placeholder={OPPONENT_DEFAULT_NAME}
          onChange={(event) => {
            onChange({ ...value, opponentName: event.target.value });
          }}
        />
      </Field>
      <AgentChoiceField
        label="Hint strength"
        value={value.hint}
        agents={agents}
        onChange={(hint) => {
          onChange({ ...value, hint });
        }}
      />
    </>
  );
}

function WatchGameSetup({
  value,
  agents,
  onChange,
}: ScenarioSetupProps<WatchGameChoices>) {
  return (
    <>
      <p className="text-muted-foreground">
        Always on this screen: start, pause and step through the match.
      </p>
      <div className="grid gap-6 sm:grid-cols-2">
        <AgentChoiceField
          label="White agent"
          value={value.white}
          agents={agents}
          onChange={(white) => {
            onChange({ ...value, white });
          }}
        />
        <AgentChoiceField
          label="Black agent"
          value={value.black}
          agents={agents}
          onChange={(black) => {
            onChange({ ...value, black });
          }}
        />
      </div>
    </>
  );
}

type NewGameStep = "scenario" | "setup";

interface NewGameFlowProps {
  agents: NewGameAgents;
  initialChoices: NewGameChoices;
  /** Whether the choices were remembered, which starts the flow at the setup step. */
  remembered: boolean;
  onCreated: (gameId: string) => void;
}

/**
 * The new game flow: choose a scenario, then set it up.
 *
 * The choices are remembered on this device once a game is created, and the flow then
 * opens at the setup of the last scenario, so a similar game takes two taps.
 */
export function NewGameFlow({
  agents,
  initialChoices,
  remembered,
  onCreated,
}: NewGameFlowProps) {
  const nameId = useId();
  const [step, setStep] = useState<NewGameStep>(remembered ? "setup" : "scenario");
  const [choices, setChoices] = useState(initialChoices);
  const [name, setName] = useState("");
  const createGame = useCreateGame();
  const info = GAME_SCENARIO_INFO[choices.scenario];
  const placeholder = defaultGameName(choices, agents);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const request = buildNewGameRequest({ choices, agents, name, random: Math.random });

    if (request === null) {
      return;
    }

    createGame.mutate(request, {
      onSuccess: (game) => {
        writeNewGameChoices(choices);
        toast.success(`Created ${game.name}.`);
        onCreated(game.id);
      },
    });
  };

  let setup: ReactNode;

  switch (choices.scenario) {
    case "agent":
      setup = (
        <AgentGameSetup
          value={choices.agentGame}
          agents={agents}
          onChange={(agentGame) => {
            setChoices({ ...choices, agentGame });
          }}
        />
      );
      break;
    case "hints":
      setup = (
        <HintsGameSetup
          value={choices.hintsGame}
          agents={agents}
          onChange={(hintsGame) => {
            setChoices({ ...choices, hintsGame });
          }}
        />
      );
      break;
    case "watch":
      setup = (
        <WatchGameSetup
          value={choices.watchGame}
          agents={agents}
          onChange={(watchGame) => {
            setChoices({ ...choices, watchGame });
          }}
        />
      );
      break;
  }

  if (step === "scenario") {
    return (
      <>
        <DialogHeader className="border-b p-4 pr-12">
          <DialogTitle>New game</DialogTitle>
          <DialogDescription>What would you like to do?</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          <ScenarioCards
            value={remembered ? choices.scenario : null}
            onChoose={(scenario) => {
              setChoices({ ...choices, scenario });
              setStep("setup");
            }}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <DialogHeader className="flex-row items-center gap-2 border-b p-4 pr-12">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="Back to the scenarios"
          onClick={() => {
            setStep("scenario");
          }}
        >
          <ChevronLeftIcon />
        </Button>
        <div className="flex flex-col gap-1">
          <DialogTitle>{info.title}</DialogTitle>
          <DialogDescription>{info.description}</DialogDescription>
        </div>
      </DialogHeader>
      <form className="flex min-h-0 flex-1 flex-col" onSubmit={submit}>
        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4">
          {setup}
          <Field>
            <FieldLabel htmlFor={nameId}>Name (optional)</FieldLabel>
            <Input
              id={nameId}
              value={name}
              maxLength={GAME_NAME_MAX_LENGTH}
              placeholder={placeholder ?? ""}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </Field>
        </div>
        <div className="flex justify-end border-t p-4">
          <Button
            type="submit"
            className="w-full sm:w-auto"
            disabled={placeholder === null || createGame.isPending}
          >
            Start game
          </Button>
        </div>
      </form>
    </>
  );
}

interface NewGameLoaderProps {
  onCreated: (gameId: string) => void;
}

/** The first step's header with a message while the agents load or fail. */
function NewGameMessage({ children }: { children: ReactNode }) {
  return (
    <>
      <DialogHeader className="border-b p-4 pr-12">
        <DialogTitle>New game</DialogTitle>
        <DialogDescription>What would you like to do?</DialogDescription>
      </DialogHeader>
      <div className="p-4">{children}</div>
    </>
  );
}

/** Load the agents and the remembered choices, then show the flow. */
function NewGameLoader({ onCreated }: NewGameLoaderProps) {
  const agentKinds = useAgentKinds();
  const presets = useAgentPresets();

  if (agentKinds.isError || presets.isError) {
    const error = agentKinds.error ?? presets.error;

    return (
      <NewGameMessage>
        <p className="text-destructive">Could not load the agents: {error?.message}</p>
      </NewGameMessage>
    );
  }

  if (!agentKinds.isSuccess || !presets.isSuccess) {
    return (
      <NewGameMessage>
        <p className="text-muted-foreground">Loading agents…</p>
      </NewGameMessage>
    );
  }

  const agents = { agentKinds: agentKinds.data, presets: presets.data };
  const defaults = defaultNewGameChoices(agents);

  if (defaults === null) {
    return (
      <NewGameMessage>
        <p className="text-destructive">No agents are available.</p>
      </NewGameMessage>
    );
  }

  const stored = readNewGameChoices(defaults, agents);

  return (
    <NewGameFlow
      agents={agents}
      initialChoices={stored ?? defaults}
      remembered={stored !== null}
      onCreated={onCreated}
    />
  );
}

/**
 * The button that opens the new game flow, which opens the game once created.
 *
 * On a phone the flow is a full-screen sheet; on a desktop it is a dialog.
 */
export function NewGameDialog() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <PlusIcon />
          New game
        </Button>
      </DialogTrigger>
      <DialogContent className="top-0 left-0 flex h-dvh max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none p-0 sm:top-1/2 sm:left-1/2 sm:h-auto sm:max-h-[90dvh] sm:max-w-2xl sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl">
        {open && (
          <NewGameLoader
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
