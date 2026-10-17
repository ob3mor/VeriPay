import type { LucideIcon } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Shared scaffold for the dashboard placeholder pages: states what the page
 * will become and which API surface it will consume (docs/API.md §6 endpoint
 * map), so reviewers can trace every planned call back to the contract.
 * Pure server component — no data fetching, static-export friendly.
 */
export function PlaceholderPage({
  title,
  description,
  phase,
  icon: Icon,
  points,
}: {
  title: string;
  description: string;
  phase: string;
  icon: LucideIcon;
  points: string[];
}) {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{description}</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
              <Icon className="h-5 w-5 text-muted-foreground" />
            </span>
            <div>
              <CardTitle className="text-base">Placeholder page</CardTitle>
              <CardDescription>Ships in {phase} — this scaffold ships the shell only.</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <ul className="max-w-2xl space-y-2.5 text-sm text-muted-foreground">
            {points.map((point) => (
              <li key={point} className="flex gap-2.5">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/50" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
