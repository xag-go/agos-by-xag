"use client";

import { useState, useTransition } from "react";
import type { FileDiff, SkillVersion } from "@/data/types";
import { cn } from "@/shared/ui/cn";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import {
  readSkillVersionDiff,
  readSkillVersions,
  restoreSkillVersion,
} from "./skill-studio-actions";

// ---- Versions -----------------------------------------------------------------------

const AUTHOR: Record<string, string> = {
  owner: "You",
  cofounder: "Co-Founder",
  curator: "The skills curator",
  hub: "The skills hub",
  outside: "Outside the skill tool",
};

export function when(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : new Date(t).toLocaleString();
}

function size(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

export function VersionsTab({
  workspaceId,
  itemId,
  initial,
}: {
  workspaceId: string;
  itemId: number;
  initial: SkillVersion[];
}) {
  const [versions, setVersions] = useState(initial);
  const [pair, setPair] = useState<{ a: number; b: number } | null>(null);
  const [diff, setDiff] = useState<FileDiff[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const { dialog, confirm } = useAsk();
  const latest = versions[0]?.number ?? 0;

  function showDiff(a: number, b: number) {
    setPair({ a, b });
    setDiff(null);
    start(async () => {
      setDiff(await readSkillVersionDiff(workspaceId, itemId, a, b));
    });
  }

  function restore(number: number) {
    void (async () => {
      const ok = await confirm({
        title: `Restore version ${number}?`,
        body: `The skill's folder becomes version ${number}, as one write. The current state stays as version ${latest}: restoring it undoes this.`,
        confirmLabel: "Restore",
      });
      if (!ok) return;
      setError(null);
      setNote(null);
      start(async () => {
        const result = await restoreSkillVersion(workspaceId, itemId, number);
        if (result.error) {
          setError(result.error);
          return;
        }
        setNote(
          result.restored
            ? `Restored as version ${result.version}.${
                result.skipped?.length
                  ? ` Left as they are (the skill tool doesn't write them): ${result.skipped.join(", ")}.`
                  : ""
              }`
            : "The skill is already in that state: nothing written.",
        );
        setVersions(await readSkillVersions(workspaceId, itemId));
        setPair(null);
        setDiff(null);
      });
    })();
  }

  return (
    <div className="flex flex-col gap-4">
      {dialog}
      <p className="text-sm text-ink-2">
        Every write to this skill, from the skill ledger: who, when, what.
        Compare two versions, or restore one (the restore itself becomes the
        next version, so it can be undone by restoring the one before it).
      </p>
      {versions.length === 0 ? (
        <p className="text-sm text-ink-3">No version yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-ink-3">
            <tr>
              <th className="py-1 pr-3 font-medium">Version</th>
              <th className="py-1 pr-3 font-medium">When</th>
              <th className="py-1 pr-3 font-medium">Who</th>
              <th className="py-1 pr-3 font-medium">What</th>
              <th className="py-1 pr-3 font-medium">Size</th>
              <th className="py-1 font-medium" aria-label="Actions" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {versions.map((v, i) => {
              const previous = versions[i + 1];
              return (
                <tr key={v.number} className="align-top">
                  <td className="py-2 pr-3 font-mono">
                    v{v.number}
                    {v.number === latest && (
                      <span className="ml-1.5 rounded-full bg-sunken px-1.5 text-xs text-ink-2">
                        current
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap text-ink-2">
                    {when(v.at)}
                  </td>
                  <td className="py-2 pr-3">{AUTHOR[v.author] ?? v.author}</td>
                  <td className="py-2 pr-3">
                    {v.summary}
                    <span className="block text-xs text-ink-3">
                      {v.files.join(", ")}
                    </span>
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap text-ink-2">
                    {size(v.size)}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    <div className="flex justify-end gap-3">
                      {previous && (
                        <button
                          type="button"
                          className="text-ink-2 hover:text-ink"
                          disabled={busy}
                          onClick={() => showDiff(previous.number, v.number)}
                        >
                          Changes
                        </button>
                      )}
                      {v.number !== latest && (
                        <>
                          <button
                            type="button"
                            className="text-ink-2 hover:text-ink"
                            disabled={busy}
                            onClick={() => showDiff(v.number, latest)}
                          >
                            vs current
                          </button>
                          <button
                            type="button"
                            className="text-accent hover:underline"
                            disabled={busy}
                            onClick={() => restore(v.number)}
                          >
                            Restore
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <FormStatus error={error} saved={note !== null} savedText={note ?? ""} />
      {pair && (
        <section className="rounded-xl border border-line">
          <div className="flex items-center justify-between border-b border-line px-3 py-2 text-sm">
            <span>
              v{pair.a} → v{pair.b}
            </span>
            <button
              type="button"
              className="text-ink-2 hover:text-ink"
              onClick={() => {
                setPair(null);
                setDiff(null);
              }}
            >
              Close
            </button>
          </div>
          {diff === null ? (
            <p className="px-3 py-2 text-sm text-ink-3">Comparing…</p>
          ) : diff.length === 0 ? (
            <p className="px-3 py-2 text-sm text-ink-3">No difference.</p>
          ) : (
            diff.map((d) => <DiffBlock key={d.path} diff={d} />)
          )}
        </section>
      )}
    </div>
  );
}

function DiffBlock({ diff }: { diff: FileDiff }) {
  return (
    <div className="border-b border-line last:border-b-0">
      <p className="px-3 py-1.5 font-mono text-xs text-ink-2">{diff.path}</p>
      <pre className="overflow-x-auto px-3 pb-3 font-mono text-xs leading-5">
        {diff.diff.split("\n").map((line, i) => (
          <span
            key={i}
            className={cn(
              "block",
              line.startsWith("+") && !line.startsWith("+++")
                ? "bg-success-soft text-success"
                : line.startsWith("-") && !line.startsWith("---")
                  ? "bg-danger-soft text-danger"
                  : line.startsWith("@@")
                    ? "text-ink-3"
                    : "",
            )}
          >
            {line || " "}
          </span>
        ))}
      </pre>
    </div>
  );
}
