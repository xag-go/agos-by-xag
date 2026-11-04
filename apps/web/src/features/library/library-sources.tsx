"use client";

import { useEffect, useState, useTransition } from "react";
import type { LibraryKind } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/field";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import {
  copySkillHere,
  importFromMachine,
  inspectSkill,
  installSkill,
  listCopyableSkills,
  listOnThisMachine,
  searchWeb,
  type CopyableSkill,
  type FoundItem,
} from "./actions";
import { Panel } from "@/shared/ui/panel";

/**
 * Add from this machine's Hermes (one click), from the web (search → preview
 * with source and security scan → the owner confirms) or, for a workspace's
 * skills, from another workspace (an independent copy).
 */
export function LibrarySources({
  kind,
  workspaceId,
}: {
  kind: LibraryKind;
  workspaceId?: string;
}) {
  const [tab, setTab] = useState<"machine" | "web" | "copy" | null>(null);
  const hasMachine =
    kind === "mcp" || kind === "plugin" || (kind === "skill" && !!workspaceId);
  const hasWeb = kind === "skill" && !!workspaceId;
  const hasCopy = hasWeb; // a workspace's skills only
  if (!hasMachine && !hasWeb) return null;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {hasMachine && (
          <Button
            variant={tab === "machine" ? "primary" : "secondary"}
            onClick={() => {
              setTab(tab === "machine" ? null : "machine");
            }}
          >
            {kind === "mcp" ? "From Hermes's catalog" : "On this machine"}
          </Button>
        )}
        {hasWeb && (
          <Button
            variant={tab === "web" ? "primary" : "secondary"}
            onClick={() => {
              setTab(tab === "web" ? null : "web");
            }}
          >
            From the web
          </Button>
        )}
        {hasCopy && (
          <Button
            variant={tab === "copy" ? "primary" : "secondary"}
            onClick={() => {
              setTab(tab === "copy" ? null : "copy");
            }}
          >
            From another workspace
          </Button>
        )}
      </div>
      {tab === "machine" && <Machine kind={kind} workspaceId={workspaceId} />}
      {tab === "web" && workspaceId && <Web workspaceId={workspaceId} />}
      {tab === "copy" && workspaceId && <Copy workspaceId={workspaceId} />}
    </div>
  );
}

/** Another workspace's skill, copied in: this workspace's own from then on. */
function Copy({ workspaceId }: { workspaceId: string }) {
  const [items, setItems] = useState<CopyableSkill[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void listCopyableSkills(workspaceId).then((r) => {
      if (!live) return;
      setItems(r.items);
      setError(r.error);
    });
    return () => {
      live = false;
    };
  }, [workspaceId]);
  return (
    <Panel className="flex flex-col gap-3 p-4">
      <p className="text-sm text-ink-2">
        A full copy: changing it here never changes the other workspace&apos;s
        skill, and the other way round.
      </p>
      {items === null && !error && (
        <p className="text-sm text-ink-3">Reading the workspaces…</p>
      )}
      <FormStatus error={error} />
      {items !== null && items.length === 0 && (
        <p className="text-sm text-ink-3">No other workspace has skills.</p>
      )}
      <ul className="flex max-h-96 flex-col divide-y divide-line overflow-y-auto">
        {(items ?? []).map((item) => (
          <CopyRow key={item.id} item={item} workspaceId={workspaceId} />
        ))}
      </ul>
    </Panel>
  );
}

function CopyRow({
  item,
  workspaceId,
}: {
  item: CopyableSkill;
  workspaceId: string;
}) {
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
      <div className="min-w-56 flex-1">
        <p className="text-sm font-medium">
          {item.title}{" "}
          <span className="font-mono text-xs text-ink-3">{item.name}</span>
        </p>
        <p className="text-xs text-ink-2">From {item.workspace}</p>
      </div>
      {done ? (
        <span className="text-xs text-success">Added here</span>
      ) : (
        <Button
          className="h-8"
          disabled={busy}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await copySkillHere(workspaceId, item.id);
              if (r.error) setError(r.error);
              else setDone(true);
            });
          }}
        >
          Copy here
        </Button>
      )}
      <FormStatus error={error} className="w-full text-xs" />
    </li>
  );
}

function Machine({
  kind,
  workspaceId,
}: {
  kind: LibraryKind;
  workspaceId?: string;
}) {
  const [items, setItems] = useState<FoundItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    let live = true;
    void listOnThisMachine(kind, workspaceId).then((r) => {
      if (!live) return;
      setItems(r.items);
      setError(r.error);
      setBusy(false);
    });
    return () => {
      live = false;
    };
  }, [kind, workspaceId]);
  const shown = (items ?? []).filter(
    (i) =>
      !filter ||
      i.name.includes(filter.toLowerCase()) ||
      i.summary.toLowerCase().includes(filter.toLowerCase()),
  );
  return (
    <Panel className="flex flex-col gap-3 p-4">
      <p className="text-sm text-ink-2">
        Definitions only. Credentials are never copied; each workspace enters
        its own.
      </p>
      <Input
        value={filter}
        placeholder="Filter"
        onChange={(e) => {
          setFilter(e.target.value);
        }}
        className="max-w-xs"
      />
      {busy && items === null && (
        <p className="text-sm text-ink-3">Reading Hermes…</p>
      )}
      <FormStatus error={error} />
      {items !== null && shown.length === 0 && (
        <p className="text-sm text-ink-3">Nothing found.</p>
      )}
      <ul className="flex max-h-96 flex-col divide-y divide-line overflow-y-auto">
        {shown.map((item) => (
          <FoundRow
            key={item.origin}
            item={item}
            kind={kind}
            workspaceId={workspaceId}
          />
        ))}
      </ul>
    </Panel>
  );
}

function FoundRow({
  item,
  kind,
  workspaceId,
}: {
  item: FoundItem;
  kind: LibraryKind;
  workspaceId?: string;
}) {
  const [done, setDone] = useState(item.inLibrary);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5">
      <div className="min-w-56 flex-1">
        <p className="text-sm font-medium">
          {item.title}
          {item.trust && (
            <span className="ml-2 rounded bg-sunken px-1.5 py-0.5 text-xs font-normal text-ink-3">
              {item.trust}
            </span>
          )}
        </p>
        <p className="text-xs text-ink-2">{item.locked ?? item.summary}</p>
      </div>
      {done ? (
        <span className="text-xs text-success">
          {workspaceId ? "Added here" : "In the library"}
        </span>
      ) : (
        <Button
          className="h-8"
          disabled={busy || !item.importable}
          onClick={() => {
            setError(null);
            start(async () => {
              const r = await importFromMachine(kind, item.origin, workspaceId);
              if (r.error) setError(r.error);
              else setDone(true);
            });
          }}
        >
          Import
        </Button>
      )}
      <FormStatus error={error} className="w-full text-xs" />
    </li>
  );
}

function Web({ workspaceId }: { workspaceId: string }) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<FoundItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<FoundItem | null>(null);
  const [busy, start] = useTransition();
  return (
    <Panel className="flex flex-col gap-3 p-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setPicked(null);
          start(async () => {
            const r = await searchWeb(workspaceId, query);
            setItems(r.items);
            setError(r.error);
          });
        }}
      >
        <Input
          value={query}
          placeholder="Search skills (e.g. pdf, invoices)"
          onChange={(e) => {
            setQuery(e.target.value);
          }}
          className="max-w-sm"
        />
        <Button type="submit" disabled={busy || !query.trim()}>
          Search
        </Button>
      </form>
      <FormStatus error={error} />
      {busy && <p className="text-sm text-ink-3">Searching the skills hubs…</p>}
      {picked ? (
        <Install
          item={picked}
          workspaceId={workspaceId}
          onBack={() => {
            setPicked(null);
          }}
        />
      ) : (
        <ul className="flex max-h-96 flex-col divide-y divide-line overflow-y-auto">
          {items.map((item) => (
            <li
              key={item.origin}
              className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2.5"
            >
              <div className="min-w-56 flex-1">
                <p className="text-sm font-medium">
                  {item.name}
                  <span className="ml-2 rounded bg-sunken px-1.5 py-0.5 text-xs font-normal text-ink-3">
                    {item.trust || "community"}
                  </span>
                </p>
                <p className="font-mono text-xs text-ink-3">{item.origin}</p>
                <p className="text-xs text-ink-2">{item.summary}</p>
              </div>
              {item.inLibrary ? (
                <span className="text-xs text-success">Added here</span>
              ) : (
                <Button
                  className="h-8"
                  onClick={() => {
                    setPicked(item);
                  }}
                >
                  Review
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Install({
  item,
  workspaceId,
  onBack,
}: {
  item: FoundItem;
  workspaceId: string;
  onBack: () => void;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<string | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [busy, start] = useTransition();
  const [reading, setReading] = useState(true);
  const { dialog, confirm } = useAsk();
  useEffect(() => {
    let live = true;
    void inspectSkill(workspaceId, item.origin).then((r) => {
      if (!live) return;
      setPreview(r.preview);
      setError(r.error);
      setReading(false);
    });
    return () => {
      live = false;
    };
  }, [item.origin, workspaceId]);
  return (
    <div className="flex flex-col gap-3">
      {dialog}
      <p className="text-sm">
        <span className="font-medium">{item.name}</span> from{" "}
        <span className="font-mono text-xs">{item.origin}</span>
      </p>
      {reading && <p className="text-sm text-ink-3">Reading the skill…</p>}
      {preview && (
        <pre className="max-h-80 overflow-auto rounded-xl bg-sunken p-3 text-xs whitespace-pre-wrap text-ink-2">
          {preview}
        </pre>
      )}
      <p className="text-xs text-ink-3">
        Installing runs Hermes&apos;s security scan; a blocked verdict stops it.
        It lands in this workspace only, on at once: its Co-Founder and agents
        can use it from their next session.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
        {scan === null && !blocked && (
          <Button
            variant="primary"
            disabled={busy || !preview}
            onClick={() => {
              setError(null);
              start(async () => {
                const r = await installSkill(workspaceId, item.origin);
                if (r.error) {
                  setError(r.error);
                  setBlocked(r.blocked);
                } else setScan(r.scan || "Installed.");
              });
            }}
          >
            {busy ? "Installing…" : "Install here"}
          </Button>
        )}
        {scan === null && blocked && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => {
              void (async () => {
                if (
                  !(await confirm({
                    title: `Install ${item.name} anyway?`,
                    body: "Hermes's security scan flagged it (the finding is shown above). Install only if you read it and trust it. It lands in this workspace only.",
                    confirmLabel: "Install anyway",
                    danger: true,
                  }))
                )
                  return;
                setError(null);
                start(async () => {
                  const r = await installSkill(workspaceId, item.origin, true);
                  if (r.error) setError(r.error);
                  else {
                    setBlocked(false);
                    setScan(r.scan || "Installed.");
                  }
                });
              })();
            }}
          >
            {busy ? "Installing…" : "Install anyway"}
          </Button>
        )}
        <FormStatus error={error} />
      </div>
      {scan && (
        <pre className="rounded-xl border border-success/40 bg-success-soft/40 p-3 text-xs whitespace-pre-wrap text-ink">
          {scan}
        </pre>
      )}
    </div>
  );
}
