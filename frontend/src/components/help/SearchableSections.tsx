import { SearchIcon } from "lucide-react";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { Input } from "@/components/ui/input";
import { helpTextMatches } from "@/lib/help";

interface SearchableSectionsProps {
  /** What is searched, read out as the label of the search field. */
  label: string;
  /** The `HelpSection`s to filter. */
  children: ReactNode;
}

/**
 * A search field above the sections of a help page that hides every section without all
 * the words searched for, in its headings, text and captions.
 */
export function SearchableSections({ label, children }: SearchableSectionsProps) {
  const [query, setQuery] = useState("");
  const sectionsRef = useRef<HTMLDivElement>(null);
  const emptyRef = useRef<HTMLParagraphElement>(null);

  // The sections are filtered by their rendered text, so no text is kept twice, and the
  // message for no match shows when every section is hidden.
  useLayoutEffect(() => {
    const sections =
      sectionsRef.current?.querySelectorAll<HTMLElement>("[data-help-section]") ?? [];
    let count = 0;

    for (const section of sections) {
      const match = helpTextMatches(section.textContent, query);
      section.hidden = !match;
      count += match ? 1 : 0;
    }

    if (emptyRef.current !== null) {
      emptyRef.current.hidden = count > 0;
    }
  }, [query]);

  return (
    <>
      <div className="relative">
        <SearchIcon
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          type="search"
          aria-label={label}
          placeholder="Search, for example beetle or hint"
          value={query}
          className="h-10 bg-card pl-9"
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
      </div>
      <div ref={sectionsRef} className="flex flex-col gap-4">
        {children}
      </div>
      <p ref={emptyRef} hidden className="text-muted-foreground">
        Nothing matches “{query.trim()}”.
      </p>
    </>
  );
}
