import { InfoIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { HELP_LINK_CLASSES } from "@/lib/help";
import { cn } from "@/lib/utils";

interface HelpButtonProps {
  /** What the button helps with, read out as `Help with …`. */
  topic: string;
  title: string;
  /** The short answer. */
  children: ReactNode;
  /** The help or rules section with the full answer. */
  to: string;
  className?: string;
}

/**
 * An info icon that opens a short answer, with a link to the section of the help that
 * explains more.
 */
export function HelpButton({ topic, title, children, to, className }: HelpButtonProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={`Help with ${topic}`}
          className={className}
        >
          <InfoIcon />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(20rem,calc(100vw-2rem))]">
        <PopoverHeader>
          <PopoverTitle>{title}</PopoverTitle>
          <div className="flex flex-col gap-2 text-muted-foreground">{children}</div>
        </PopoverHeader>
        <Link to={to} className={cn(HELP_LINK_CLASSES, "self-start")}>
          More in the help
        </Link>
      </PopoverContent>
    </Popover>
  );
}
