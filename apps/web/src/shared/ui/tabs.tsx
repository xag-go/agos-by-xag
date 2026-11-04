"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { cn } from "./cn";

export type TabItem = {
  id: string;
  label: string;
  count?: number;
  content: ReactNode;
};

/** Accessible tabs: arrow keys move between tabs, only the active one is tabbable. */
export function Tabs({
  items,
  initial,
}: {
  items: TabItem[];
  initial?: string;
}) {
  const [active, setActive] = useState(initial ?? items[0]?.id);
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function move(from: number, delta: number) {
    const next = (from + delta + items.length) % items.length;
    const item = items[next];
    if (!item) return;
    setActive(item.id);
    refs.current[next]?.focus();
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        role="tablist"
        className="flex gap-1 overflow-x-auto border-b border-line px-5"
      >
        {items.map((item, index) => {
          const selected = item.id === active;
          return (
            <button
              key={item.id}
              ref={(el) => {
                refs.current[index] = el;
              }}
              role="tab"
              type="button"
              id={`${base}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${base}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setActive(item.id)}
              onKeyDown={(e) => {
                if (e.key === "ArrowRight") move(index, 1);
                if (e.key === "ArrowLeft") move(index, -1);
              }}
              className={cn(
                "-mb-px flex h-10 items-center gap-1.5 border-b-2 px-2.5 text-sm whitespace-nowrap",
                selected
                  ? "border-accent font-medium text-ink"
                  : "border-transparent text-ink-2 hover:text-ink",
              )}
            >
              {item.label}
              {item.count !== undefined && item.count > 0 && (
                <span className="rounded-full bg-sunken px-1.5 text-xs text-ink-2">
                  {item.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {items.map((item) => (
        <div
          key={item.id}
          role="tabpanel"
          id={`${base}-panel-${item.id}`}
          aria-labelledby={`${base}-tab-${item.id}`}
          hidden={item.id !== active}
          className="min-h-0 flex-1 overflow-y-auto px-5 py-5"
        >
          {item.content}
        </div>
      ))}
    </div>
  );
}
