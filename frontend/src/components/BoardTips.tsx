import { LightbulbIcon, XIcon } from "lucide-react";
import { Link } from "react-router";

import type { BoardTipsState } from "@/components/useBoardTips";
import { Button } from "@/components/ui/button";
import type { BoardTip } from "@/lib/gameHelp";
import { HELP_LINK_CLASSES } from "@/lib/help";

/** The tips for the current state that are not dismissed, each with a dismiss button. */
export function BoardTips({ tips, state }: { tips: BoardTip[]; state: BoardTipsState }) {
  const shown = state.enabled
    ? tips.filter((tip) => !state.dismissed.includes(tip.id))
    : [];

  if (shown.length === 0) {
    return null;
  }

  return (
    <ul aria-label="Tips" className="flex flex-col gap-1.5">
      {shown.map((tip) => (
        <li
          key={tip.id}
          className="flex items-center gap-2 rounded-lg bg-secondary py-1 pr-1 pl-3 text-sm"
        >
          <LightbulbIcon
            aria-hidden="true"
            className="size-4 shrink-0 text-muted-foreground"
          />
          <span className="min-w-0 flex-1">
            {tip.text}
            {tip.link && (
              <>
                {" "}
                <Link to={tip.link.to} className={HELP_LINK_CLASSES}>
                  {tip.link.label}
                </Link>
              </>
            )}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Dismiss the tip ${tip.text}`}
            onClick={() => {
              state.dismiss(tip.id);
            }}
          >
            <XIcon />
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** The Tips on and off switch, remembered per device. */
export function TipsToggle({ state }: { state: BoardTipsState }) {
  return (
    <Button variant="outline" aria-pressed={state.enabled} onClick={state.toggle}>
      <LightbulbIcon />
      Tips
    </Button>
  );
}
