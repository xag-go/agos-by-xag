"use client";

import { useState, useTransition } from "react";
import type { CardService } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { FormStatus } from "@/shared/ui/form-status";
import { stopCardService } from "./card-actions";

/** The dev servers / previews the card's worker started (Hermes's background
 * processes): open the preview (AGOS's own address, never public) or stop it. */
export function CardServices({
  workspaceId,
  services,
  labelClass,
}: {
  workspaceId: string;
  services: CardService[];
  labelClass: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  if (services.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <p className={labelClass}>Services</p>
      <ul className="flex flex-col gap-2">
        {services.slice(0, 8).map((s) => (
          <li
            key={s.id}
            className="flex flex-col gap-1 rounded-lg border border-line px-2.5 py-2 text-sm"
          >
            <div className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn(
                  "size-1.5 shrink-0 rounded-full",
                  s.running && s.answering && "bg-success",
                  s.running && !s.answering && "bg-attention",
                  !s.running && "border border-ink-3",
                )}
              />
              <span className="min-w-0 flex-1 truncate font-medium">
                {s.label || s.command}
              </span>
              <span className="font-mono text-xs text-ink-3">:{s.port}</span>
            </div>
            <p
              className="truncate font-mono text-xs text-ink-3"
              title={s.command}
            >
              {s.command}
            </p>
            {s.running ? (
              <div className="flex items-center gap-2">
                <a
                  href={s.preview}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-accent underline underline-offset-2"
                >
                  {s.answering ? "Open preview" : "Open preview (starting…)"}
                </a>
                <Button
                  variant="ghost"
                  className="ml-auto h-7 px-2 text-xs"
                  disabled={busy}
                  onClick={() => {
                    start(async () => {
                      setError(
                        (await stopCardService(workspaceId, s.id)).error,
                      );
                    });
                  }}
                >
                  Stop
                </Button>
              </div>
            ) : (
              <p className="text-xs text-ink-3">Stopped</p>
            )}
          </li>
        ))}
      </ul>
      <FormStatus error={error} />
    </section>
  );
}
