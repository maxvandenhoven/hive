/*
 * The sections of the help and the rules reference, which help buttons and board tips
 * link to. The pages give each section an element with its id, and a test checks that
 * every id here has one.
 */

/** A section of the help page at `/help`. */
export type HelpSection =
  "scenarios" | "board" | "controls" | "games" | "leaving" | "rules";

/** The sections of the help page, in page order, with their headings. */
export const HELP_SECTIONS: readonly { id: HelpSection; title: string }[] = [
  { id: "scenarios", title: "What you can do" },
  { id: "board", title: "Reading the board" },
  { id: "controls", title: "Controls" },
  { id: "games", title: "Games and statuses" },
  { id: "leaving", title: "Leaving and coming back" },
  { id: "rules", title: "Rules" },
];

/** A section of the rules reference at `/help/rules`. */
export type RulesSection =
  | "goal"
  | "placement"
  | "one-hive"
  | "freedom"
  | "queen"
  | "beetle"
  | "grasshopper"
  | "spider"
  | "ant"
  | "passing"
  | "end";

/** The sections of the rules reference, in page order, with their headings. */
export const RULES_SECTIONS: readonly { id: RulesSection; title: string }[] = [
  { id: "goal", title: "Pieces and goal" },
  { id: "placement", title: "Turns and placing pieces" },
  { id: "one-hive", title: "One hive" },
  { id: "freedom", title: "Freedom to move" },
  { id: "queen", title: "Queen bee" },
  { id: "beetle", title: "Beetle" },
  { id: "grasshopper", title: "Grasshopper" },
  { id: "spider", title: "Spider" },
  { id: "ant", title: "Soldier ant" },
  { id: "passing", title: "Passing" },
  { id: "end", title: "The end of the game" },
];

/** The path of the rules reference. */
export const RULES_PATH = "/help/rules";

/** The link to a section of the help page. */
export function helpPath(section: HelpSection): string {
  return `/help#${section}`;
}

/** The link to a section of the rules reference. */
export function rulesPath(section: RulesSection): string {
  return `${RULES_PATH}#${section}`;
}

/** A link in the text of the help, foreground text with a honey underline. */
export const HELP_LINK_CLASSES =
  "font-medium underline decoration-primary decoration-2 underline-offset-4";
