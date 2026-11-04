"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import { decideReview } from "@/features/kanban/card-actions";
import { decideProposal } from "@/features/inbox/actions";
import { runAutomationNow } from "@/features/setup/actions";
import { TAB_SECTIONS } from "@/features/workspaces/tab-sections";
import { cn } from "@/shared/ui/cn";
import { Modal } from "@/shared/ui/dialog";
import { SearchIcon } from "@/shared/ui/icons";
import {
  askToHire,
  paletteData,
  paletteSearch,
  setCofounderHeartbeat,
  type PaletteData,
  type PaletteHit,
} from "./palette-actions";
import { typing } from "@/shared/keyboard";

type Item = {
  id: string;
  label: string;
  hint: string;
  words: string;
  run: () => Promise<string | null> | string | null;
};

/** The shortcuts the workspace knows (also listed by `?`). */
const SHORTCUTS: [string, string][] = [
  ["⌘K / Ctrl+K", "Command palette: actions and search"],
  ["g i", "Go to the Inbox"],
  ["g k", "Go to the Kanban"],
  ["g v", "Go to the Vision"],
  ["g h", "Go to the Hierarchy"],
  ["g a", "Go to the Automations"],
  ["g s", "Go to the Settings"],
  ["c", "New card"],
  ["?", "These shortcuts"],
];

const GO: Record<string, string> = {
  i: "/inbox",
  k: "/kanban",
  v: "/vision",
  h: "/hierarchy",
  a: "/automations",
  s: "/settings",
};

function matches(item: Item, query: string): boolean {
  const hay = `${item.label} ${item.words}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => hay.includes(w));
}

/**
 * The workspace's command palette (⌘K / Ctrl+K, or the button at the title's
 * right): its actions (new card, new automation, go to a page, switch workspace,
 * open the Inbox, approve the top Inbox item, hire, run an automation now, the
 * Co-Founder's heartbeat) and live search results; and the keyboard shortcuts
 * (`g i`, `g k`, `g v`, `c`, `?`). Nothing is kept: each opening reads the core.
 */
export function CommandPalette({ workspaceId }: { workspaceId: string }) {
  const [open, setOpen] = useState(false);
  const [help, setHelp] = useState(false);
  const router = useRouter();
  const base = `/w/${encodeURIComponent(workspaceId)}`;

  useEffect(() => {
    let leader = 0;
    const onKey = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        !event.altKey &&
        !event.shiftKey &&
        event.key.toLowerCase() === "k"
      ) {
        event.preventDefault();
        setOpen(true);
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (typing(event.target, { dialogs: true })) return;
      const key = event.key;
      if (leader && Date.now() - leader < 1200) {
        leader = 0;
        const path = GO[key.toLowerCase()];
        if (path) {
          event.preventDefault();
          router.push(`${base}${path}`);
        }
        return;
      }
      if (key === "g") {
        leader = Date.now();
      } else if (key === "c") {
        event.preventDefault();
        router.push(`${base}/kanban?new=1`, { scroll: false });
      } else if (key === "?") {
        event.preventDefault();
        setHelp(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [base, router]);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen(true);
        }}
        title="Actions and search (⌘K / Ctrl+K) · shortcuts: ?"
        className="hidden h-8 items-center gap-2 rounded-lg border border-line px-2.5 text-xs text-ink-3 transition-colors hover:text-ink sm:inline-flex"
      >
        <SearchIcon />
        Search
        <kbd className="rounded border border-line px-1 font-sans text-micro">
          ⌘K
        </kbd>
      </button>
      {open && (
        <Palette
          workspaceId={workspaceId}
          onClose={() => {
            setOpen(false);
          }}
          onHelp={() => {
            setOpen(false);
            setHelp(true);
          }}
        />
      )}
      {help && (
        <Modal
          label="Keyboard shortcuts"
          onClose={() => {
            setHelp(false);
          }}
        >
          <div className="flex flex-col gap-3 p-5">
            <h2 className="font-display text-base font-semibold">
              Keyboard shortcuts
            </h2>
            <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-sm">
              {SHORTCUTS.map(([keys, what]) => (
                <div key={keys} className="contents">
                  <dt>
                    <kbd className="rounded border border-line px-1.5 py-0.5 font-mono text-xs">
                      {keys}
                    </kbd>
                  </dt>
                  <dd className="text-ink-2">{what}</dd>
                </div>
              ))}
            </dl>
            <p className="text-xs text-ink-3">
              Shortcuts work anywhere in the workspace except while typing.
            </p>
          </div>
        </Modal>
      )}
    </>
  );
}

function Palette({
  workspaceId,
  onClose,
  onHelp,
}: {
  workspaceId: string;
  onClose: () => void;
  onHelp: () => void;
}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [data, setData] = useState<PaletteData | null>(null);
  const [hits, setHits] = useState<PaletteHit[]>([]);
  const [active, setActive] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const base = `/w/${encodeURIComponent(workspaceId)}`;

  useEffect(() => {
    input.current?.focus();
    let alive = true;
    void paletteData(workspaceId).then((d) => {
      if (alive) setData(d);
    });
    return () => {
      alive = false;
    };
  }, [workspaceId]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) return;
    let alive = true;
    const timer = setTimeout(() => {
      void paletteSearch(workspaceId, q).then((found) => {
        if (alive) setHits(found);
      });
    }, 200);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [query, workspaceId]);

  const items = useMemo(() => {
    const go = (path: string) => () => {
      router.push(`${base}${path}`);
      return null;
    };
    const out: Item[] = [
      {
        id: "new-card",
        label: "New card",
        hint: "c",
        words: "create task kanban",
        run: go("/kanban?new=1"),
      },
      {
        id: "new-automation",
        label: "New automation",
        hint: "",
        words: "create schedule job",
        run: go("/automations?new=1"),
      },
      {
        id: "inbox",
        label: "Open Inbox",
        hint: "g i",
        words: "waiting approve",
        run: go("/inbox"),
      },
    ];
    const top = data?.top;
    if (top) {
      out.push({
        id: "approve-top",
        label: `Approve: ${top.title}`,
        hint: "Inbox",
        words: "approve top inbox yes accept",
        run: async () => {
          const result =
            top.kind === "proposal" && top.askId !== null
              ? await decideProposal(workspaceId, top.askId, "approve")
              : await decideReview(workspaceId, top.card, "approve");
          return result.error ?? `Approved: ${top.title}`;
        },
      });
    }
    const role = /^hire\b\s*(.*)$/i.exec(query.trim())?.[1] ?? "";
    out.push({
      id: "hire",
      label: role ? `Hire: ${role}` : "Hire a new member…",
      hint: "Co-Founder",
      words: "hire member recruit team",
      run: async () => {
        await askToHire(workspaceId, role);
        return null;
      },
    });
    const hb = data?.heartbeat;
    if (hb) {
      out.push({
        id: "heartbeat",
        label: hb.on
          ? "Turn the Co-Founder's heartbeat off"
          : "Turn the Co-Founder's heartbeat on",
        hint: hb.on ? `on · ${hb.interval}` : "off",
        words: "heartbeat toggle co-founder",
        run: async () => {
          const result = await setCofounderHeartbeat(
            workspaceId,
            !hb.on,
            hb.interval,
          );
          if (!result.error)
            setData((d) =>
              d ? { ...d, heartbeat: { ...hb, on: !hb.on } } : d,
            );
          return result.error ?? `Heartbeat ${hb.on ? "off" : "on"}.`;
        },
      });
    }
    for (const a of data?.automations ?? []) {
      out.push({
        id: `run-${String(a.id)}`,
        label: `Run now: ${a.name}`,
        hint: a.on ? "automation" : "automation (off)",
        words: "run automation now start",
        run: async () => {
          const result = await runAutomationNow(workspaceId, a.id);
          return result.error ?? `${a.name} runs within a minute.`;
        },
      });
    }
    for (const [key, s] of Object.entries(TAB_SECTIONS)) {
      out.push({
        id: `go-${key}`,
        label: `Go to ${s.label}`,
        hint: "page",
        words: `go open page ${key}`,
        run: go(s.path || "/"),
      });
    }
    for (const [path, label] of [
      ["/settings", "Settings"],
      ["/automations#rules", "Automations → Rules"],
      ["/settings/connections", "Settings → Connections"],
    ] as const) {
      out.push({
        id: `go${path}`,
        label: `Go to ${label}`,
        hint: "page",
        words: "go open settings",
        run: go(path),
      });
    }
    for (const w of data?.workspaces ?? []) {
      if (w.id === workspaceId) continue;
      out.push({
        id: `ws-${w.id}`,
        label: `Switch to ${w.name}`,
        hint: "workspace",
        words: "switch workspace project",
        run: () => {
          router.push(`/w/${encodeURIComponent(w.id)}`);
          return null;
        },
      });
    }
    out.push({
      id: "shortcuts",
      label: "Keyboard shortcuts",
      hint: "?",
      words: "help keys",
      run: () => {
        onHelp();
        return null;
      },
    });
    const q = query.trim();
    const shown = q
      ? out.filter((i) =>
          i.id === "hire" ? /^hire\b/i.test(q) || matches(i, q) : matches(i, q),
        )
      : out;
    if (q) {
      shown.push({
        id: "search",
        label: `Search for “${q}”`,
        hint: "Enter on the Search page",
        words: "",
        run: go(`/search?q=${encodeURIComponent(q)}`),
      });
      for (const [n, h] of (q.length >= 2 ? hits : []).entries()) {
        shown.push({
          id: `hit-${String(n)}`,
          label: h.title,
          hint: h.where ? `${h.type} · ${h.where}` : h.type,
          words: "",
          run: () => {
            router.push(h.href);
            return null;
          },
        });
      }
    }
    return shown;
  }, [base, data, hits, onHelp, query, router, workspaceId]);

  const pick = (item: Item | undefined) => {
    if (!item || busy) return;
    start(async () => {
      const said = await item.run();
      if (said === null) onClose();
      else setNote(said);
    });
  };

  return (
    <Modal label="Actions and search" onClose={onClose}>
      <div className="flex items-center gap-2 border-b border-line p-3">
        <SearchIcon />
        <input
          ref={input}
          value={query}
          maxLength={200}
          aria-label="Type an action or search"
          placeholder="Type an action or search… (new card, go to vision, hire editor)"
          className="h-10 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-3"
          onChange={(event) => {
            setQuery(event.currentTarget.value);
            setActive(0);
            setNote(null);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActive((a) => Math.min(a + 1, items.length - 1));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              pick(items[active]);
            }
          }}
        />
        <kbd className="rounded border border-line px-1.5 text-xs text-ink-3">
          Esc
        </kbd>
      </div>
      {note && (
        <p
          role="status"
          className="border-b border-line px-4 py-2 text-sm text-ink-2"
        >
          {note}
        </p>
      )}
      <ul
        role="listbox"
        aria-label="Actions"
        className="max-h-[50dvh] overflow-y-auto p-1.5"
      >
        {items.map((item, i) => (
          <li key={item.id} role="option" aria-selected={i === active}>
            <button
              type="button"
              disabled={busy}
              onMouseEnter={() => {
                setActive(i);
              }}
              onClick={() => {
                pick(item);
              }}
              className={cn(
                "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm",
                i === active ? "bg-sunken text-ink" : "text-ink-2",
              )}
            >
              <span className="truncate">{item.label}</span>
              {item.hint && (
                <span className="shrink-0 text-xs text-ink-3">{item.hint}</span>
              )}
            </button>
          </li>
        ))}
        {items.length === 0 && (
          <li className="px-3 py-2 text-sm text-ink-3">Nothing matches.</li>
        )}
      </ul>
    </Modal>
  );
}
