/*
 * The two help pages linked from the game list, how the app works and the rules, and
 * their sections. The pages give each section an element with its id, and a test checks
 * that every id here has one.
 */

/** The path of the page on how the app works. */
export const HELP_PATH = "/help";

/** A section of the page on how the app works. */
export type HelpSection = "scenarios" | "board" | "controls" | "games" | "leaving";

/** The sections of the page on how the app works, in page order, with their headings. */
export const HELP_SECTIONS: readonly { id: HelpSection; title: string }[] = [
  { id: "scenarios", title: "Creating a game" },
  { id: "board", title: "Colours and marks on the board" },
  { id: "controls", title: "Controls" },
  { id: "games", title: "Games and statuses" },
  { id: "leaving", title: "Leaving and coming back" },
];

/** A section of the rules reference. */
export type RulesSection =
  | "pieces"
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
  { id: "pieces", title: "The pieces" },
  { id: "goal", title: "Goal of the game" },
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
export const RULES_PATH = "/rules";

/** A link in the text of the help, foreground text with a honey underline. */
export const HELP_LINK_CLASSES =
  "font-medium underline decoration-primary decoration-2 underline-offset-4";

/** Whether a help text holds every word of a search, ignoring case; an empty one does. */
export function helpTextMatches(text: string, query: string): boolean {
  const haystack = text.toLowerCase();

  return query
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word.length > 0)
    .every((word) => haystack.includes(word));
}
