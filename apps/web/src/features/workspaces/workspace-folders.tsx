"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";
import type { BotRestart, WorkspaceFolder } from "@/data/types";
import { Button } from "@/shared/ui/button";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import {
  addFolder,
  botRestart,
  removeFolder,
  setFolderAccess,
} from "./actions";
import { FolderPicker } from "./folder-picker";
import type { FormState } from "@/server/form";

export function Folders({
  workspaceId,
  folders,
}: {
  workspaceId: string;
  folders: WorkspaceFolder[];
}) {
  const restart = useBotRestart(workspaceId);
  const [state, action, pending] = useActionState(
    async (prev: FormState, form: FormData) => {
      const done = await addFolder(workspaceId, prev, form);
      if (!done.error) restart.watch();
      return done;
    },
    { error: null },
  );
  const [picking, setPicking] = useState(false);
  const [path, setPath] = useState("");
  return (
    <section className="flex flex-col gap-4" aria-labelledby="folders-title">
      <div>
        <h2 id="folders-title" className="font-display text-base font-semibold">
          Folders
        </h2>
        <p className="mt-1 text-sm text-ink-2">
          Everything this workspace&apos;s agents can see. Nothing else exists
          for them — not even if you ask in a chat.
        </p>
        {restart.said?.state === "restarting" ? (
          <p role="status" className="mt-2 text-sm text-ink-2">
            Restarting the bot…
          </p>
        ) : restart.said?.state === "failed" ? (
          <FormStatus error={restart.said.reason} className="mt-2" />
        ) : null}
      </div>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {folders.map((f) => (
          <li
            key={f.own ? "own" : `shared:${f.name}`}
            className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5 text-sm"
          >
            <span className="font-medium">
              {f.own ? "/workspace" : `/shared/${f.name}`}
            </span>
            <span
              className="min-w-0 truncate text-ink-3"
              title={f.hostPath ?? undefined}
            >
              {f.own ? "This workspace's own folder" : f.hostPath}
            </span>
            {f.own ? (
              <span className="ml-auto text-xs text-ink-3">
                Read and write · can&apos;t be removed
              </span>
            ) : (
              <span className="ml-auto flex items-center gap-2">
                {/* Keyed by the access Hermes holds: React resets a form once
                    its action is done, and an uncontrolled <select> goes back
                    to the value it was first drawn with (a new defaultValue
                    is ignored), so the box showed the old access until a
                    reload. A new access from the page's refresh draws a new
                    box with it. */}
                <form
                  key={f.access}
                  action={async (form) => {
                    await setFolderAccess(workspaceId, f.name, form);
                    restart.watch();
                  }}
                >
                  <Select
                    name="access"
                    aria-label={`Access to ${f.name}`}
                    defaultValue={f.access}
                    className="h-8 !w-40"
                    onChange={(e) => e.currentTarget.form?.requestSubmit()}
                  >
                    <option value="read">Read only</option>
                    <option value="read-write">Read and write</option>
                  </Select>
                </form>
                <form
                  action={async () => {
                    await removeFolder(workspaceId, f.name);
                    restart.watch();
                  }}
                >
                  <Button type="submit" variant="ghost" className="h-8">
                    Remove
                  </Button>
                </form>
              </span>
            )}
          </li>
        ))}
      </ul>
      <form
        action={action}
        className="flex flex-col gap-3 rounded-xl border border-dashed border-line-strong p-4"
      >
        <p className="text-sm font-medium">Add a folder</p>
        <div className="grid gap-3 sm:grid-cols-[1fr_11rem_auto] sm:items-end">
          <Field label="Folder">
            <div className="flex gap-2">
              <Input
                name="path"
                required
                readOnly
                value={path}
                placeholder="Choose a folder…"
                onClick={() => {
                  setPicking(true);
                }}
                className="cursor-pointer"
              />
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setPicking(true);
                }}
              >
                Browse…
              </Button>
            </div>
          </Field>
          <Field label="Access">
            <Select name="access" defaultValue="read">
              <option value="read">Read only</option>
              <option value="read-write">Read and write</option>
            </Select>
          </Field>
          <Button type="submit" disabled={pending || !path}>
            Add folder
          </Button>
        </div>
        <FormStatus
          error={state.error}
          saved={state.saved}
          savedText="Folder added."
        />
      </form>
      <FolderPicker
        open={picking}
        onClose={() => {
          setPicking(false);
        }}
        onPick={(p) => {
          setPath(p);
          setPicking(false);
        }}
      />
    </section>
  );
}

/** The gateway restart a folder click starts after its answer (the core's
 * gateway-restart): "Restarting the bot…" while it runs, its reason when it
 * failed, and the page read again once it is done. Asked on open (a restart
 * still running shows) and after each folder click, every 2 s while it runs,
 * never while the tab is hidden. */
function useBotRestart(workspaceId: string) {
  const router = useRouter();
  const [said, setSaid] = useState<BotRestart | null>(null);
  const [clicks, setClicks] = useState(0);
  useEffect(() => {
    let stopped = false;
    let live = true; // until the restart is known to be over
    let asking = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ask = async () => {
      timer = undefined;
      if (stopped || !live || asking || document.visibilityState === "hidden")
        return;
      asking = true;
      let got: BotRestart | null = null;
      try {
        got = await botRestart(workspaceId);
      } catch {
        got = null; // the core is away a moment: asked again below
      }
      asking = false;
      if (stopped) return;
      if (got === null || got.state === "restarting") {
        if (got) setSaid(got);
        timer = setTimeout(() => void ask(), got ? 2000 : 5000);
        return;
      }
      live = false;
      setSaid(got);
      if (got.state === "done" && clicks > 0) router.refresh();
    };
    const shown = () => {
      if (document.visibilityState !== "hidden" && timer === undefined)
        void ask();
    };
    void ask();
    document.addEventListener("visibilitychange", shown);
    return () => {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      document.removeEventListener("visibilitychange", shown);
    };
  }, [workspaceId, clicks, router]);
  return {
    said,
    watch: () => {
      setSaid({ state: "restarting", reason: "" });
      setClicks((n) => n + 1);
    },
  };
}
