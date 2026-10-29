import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/** One section of a help page, with an anchor, which the page search can hide. */
export function HelpSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  const headingId = `${id}-heading`;

  return (
    <section id={id} aria-labelledby={headingId} data-help-section>
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 id={headingId} className="font-heading text-lg font-semibold">
              {title}
            </h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-base leading-relaxed">
          {children}
        </CardContent>
      </Card>
    </section>
  );
}
