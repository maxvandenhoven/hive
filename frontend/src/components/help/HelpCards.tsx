import {
  BookOpenIcon,
  ChevronRightIcon,
  CircleHelpIcon,
  type LucideIcon,
} from "lucide-react";
import { Link } from "react-router";

import { HELP_PATH, RULES_PATH } from "@/lib/help";

interface HelpCardProps {
  to: string;
  icon: LucideIcon;
  title: string;
  description: string;
}

function HelpCard({ to, icon: Icon, title, description }: HelpCardProps) {
  return (
    <Link
      to={to}
      className="group flex items-center gap-4 rounded-xl bg-card p-4 shadow-xs ring-1 ring-border transition-colors outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Icon className="size-6" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-base font-semibold">{title}</span>
        <span className="text-sm text-muted-foreground">{description}</span>
      </span>
      <ChevronRightIcon className="size-5 shrink-0 text-muted-foreground" />
    </Link>
  );
}

/** The two ways into the help from the game list, the rules and how the app works. */
export function HelpCards() {
  return (
    <nav aria-label="Help" className="grid gap-3 sm:grid-cols-2">
      <HelpCard
        to={RULES_PATH}
        icon={BookOpenIcon}
        title="Game rules"
        description="How each insect moves and how to win, with diagrams."
      />
      <HelpCard
        to={HELP_PATH}
        icon={CircleHelpIcon}
        title="How the app works"
        description="Creating games, the colours on the board and the controls."
      />
    </nav>
  );
}
