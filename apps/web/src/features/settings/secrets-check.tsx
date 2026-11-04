"use client";

import { useState, useTransition } from "react";
import type { SecretsCheck } from "@/data/queries";
import { TimeAgo } from "@/shared/time-ago";
import { Button } from "@/shared/ui/button";
import { FormStatus } from "@/shared/ui/form-status";
import { runSecretsCheck } from "./secrets-check-actions";
import { PanelSection } from "@/shared/ui/panel";

function Group({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details open className="rounded-xl border border-line">
      <summary className="cursor-pointer px-4 py-2 text-sm font-medium">
        {title}
      </summary>
      <ul className="flex flex-col gap-1 px-4 pb-3 text-sm text-ink-2">
        {children}
      </ul>
    </details>
  );
}

function Findings({ data }: { data: SecretsCheck }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-ink-3">
        Last checked: <TimeAgo iso={data.checkedAt} />
      </p>
      {data.problems === 0 ? (
        <p className="text-sm text-ink-2">0 problems.</p>
      ) : (
        <p className="text-sm text-danger">
          {data.problems} problem{data.problems === 1 ? "" : "s"}
        </p>
      )}
      {data.chats.length > 0 ? (
        <Group title="Keys in chat history">
          {data.chats.map((c, n) => (
            <li key={n}>
              {c.kind} ending <code>{c.last4 || "?"}</code> · {c.workspace} ·{" "}
              {c.session || c.source || "a chat"} · {c.role}
              {c.at ? <> · {c.at.slice(0, 10)}</> : null}
            </li>
          ))}
          {data.chatsMore > 0 ? <li>and {data.chatsMore} more</li> : null}
        </Group>
      ) : null}
      {data.logs.length > 0 ? (
        <Group title="Keys in logs">
          {data.logs.map((l) => (
            <li key={`${l.workspaceId}/${l.file}`}>
              {l.workspace} · <code>{l.file}</code> · {l.count} line
              {l.count === 1 ? "" : "s"}
              {l.keys.length > 0
                ? ` (ending ${l.keys.map((k) => k.last4 || "?").join(", ")})`
                : ""}
            </li>
          ))}
        </Group>
      ) : null}
      {data.permissions.length > 0 ? (
        <Group title="Wrong permissions">
          {data.permissions.map((p) => (
            <li key={p.path}>
              <code className="break-all">{p.path}</code> · {p.mode} (should be{" "}
              {p.want})
            </li>
          ))}
        </Group>
      ) : null}
      {data.notChecked.length > 0 ? (
        <p className="text-sm text-ink-2">
          Not checked: {data.notChecked.join("; ")}
        </p>
      ) : null}
    </div>
  );
}

/** Settings → Health: the Secrets check, run when he clicks (no schedule). Only
 * reads; shows where a key sits (its kind and last 4), never the key. */
export function SecretsCheckView() {
  const [data, setData] = useState<SecretsCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  const run = () => {
    start(async () => {
      const got = await runSecretsCheck();
      if (got.ok) {
        setData(got.data);
        setError(null);
      } else setError(got.error);
    });
  };

  return (
    <PanelSection
      aria-labelledby="secrets-check"
      className="flex max-w-4xl flex-col gap-4 p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id="secrets-check" className="font-medium">
            Secrets check
          </h3>
          <p className="mt-1 text-sm text-ink-2">
            Looks for keys left in every workspace&apos;s chat history and logs
            (as Hermes&apos;s own masking sees them) and for key files others
            could read. Nothing is changed, and no key is shown: only its kind
            and last 4 characters. The Co-Founder can run it for its workspace
            from a chat too.
          </p>
        </div>
        <Button variant="primary" disabled={busy} onClick={run}>
          {busy ? "Checking…" : "Check now"}
        </Button>
      </div>
      <FormStatus error={error} />
      {data ? <Findings data={data} /> : null}
    </PanelSection>
  );
}
