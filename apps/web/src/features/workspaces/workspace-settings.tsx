"use client";

import {
  useActionState,
  useRef,
  useState,
  useTransition,
  type ReactNode,
} from "react";
import type { AccessLists } from "@/data/queries";
import type { CatalogProvider, Workspace, WorkspaceFolder } from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import {
  AutonomyTable,
  type AutonomyView,
} from "@/features/proactive/proactive-settings";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { TILE_BG, tileVars } from "@/shared/ui/hue";
import { WorkspaceTile } from "@/shared/ui/workspace-tile";
import {
  archiveWorkspace,
  deleteWorkspace,
  removeWorkspaceIcon,
  saveWorkspaceSettings,
  uploadWorkspaceIcon,
} from "./actions";
import { useAppFacts } from "@/shared/app-facts";
import type { FormState } from "@/server/form";
import { AgentAccess } from "./workspace-agent-access";
import { Folders } from "./workspace-folders";

export function WorkspaceSettings({
  workspace,
  folders,
  catalog,
  hermes,
  autonomy,
  accessLists = { deny: [], allow: [] },
}: {
  workspace: Workspace;
  folders: WorkspaceFolder[];
  catalog: CatalogProvider[];
  hermes: { values: Record<string, string>; defaults: Record<string, string> };
  autonomy: AutonomyView;
  accessLists?: AccessLists;
}) {
  const [state, action, pending] = useActionState(
    saveWorkspaceSettings.bind(null, workspace.id),
    { error: null },
  );

  return (
    <div className="flex max-w-3xl flex-col gap-10">
      <form action={action} className="flex flex-col gap-10">
        <Group title="General">
          <Field label="Display name">
            <Input name="name" defaultValue={workspace.name} required />
          </Field>
          <IconRow workspace={workspace} />
          <Field
            label="Identifier"
            hint="Fixed. It is the folder name on disk, so renaming the workspace never moves its files."
          >
            <Input value={workspace.id} readOnly disabled />
          </Field>
          <Field label="Description">
            <Textarea
              name="description"
              defaultValue={workspace.description}
              rows={2}
            />
          </Field>
        </Group>

        <Group
          title="Default model"
          description="Used by new tasks and chats. Any task or chat can override it."
        >
          <ModelPicker catalog={catalog} initial={workspace.defaultModel} />
        </Group>

        <Group
          title="Goal mode"
          description="Type /goal and what you want done, in any chat: the member keeps working on it and a judge checks after each answer whether it's done. Saved per workspace."
        >
          <Field
            label="Turns at most"
            hint={`The goal stops after this many turns, so it never uses tokens without end. Leave it empty for the default${hermes.defaults["goals.max_turns"] ? ` (${hermes.defaults["goals.max_turns"]})` : ""}.`}
          >
            <Input
              name="hermes:goals.max_turns"
              type="number"
              min={1}
              max={1000}
              defaultValue={hermes.values["goals.max_turns"]}
              placeholder={hermes.defaults["goals.max_turns"]}
              className="w-32"
            />
          </Field>
        </Group>

        <Group
          title="Telegram"
          description="The workspace's own bot is in the Channels section. Each chat can also live in a Telegram group or topic (the “Web only” button in a chat's header)."
        >
          <a
            href={`/w/${workspace.id}/settings/channels`}
            className="text-sm text-ink underline decoration-line-strong underline-offset-2 hover:decoration-ink"
          >
            Connect Telegram for this workspace
          </a>
        </Group>

        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={pending}>
            {pending ? "Saving…" : "Save changes"}
          </Button>
          <FormStatus
            error={state.error}
            saved={state.saved}
            savedText="Changes saved."
          />
        </div>
      </form>

      <AgentAccess
        workspaceId={workspace.id}
        value={workspace.chatAccess}
        lists={accessLists}
      />

      <div id="autonomy" className="scroll-mt-6">
        <AutonomyTable workspaceId={workspace.id} view={autonomy} />
      </div>

      <Folders workspaceId={workspace.id} folders={folders} />

      <DangerZone workspace={workspace} />
    </div>
  );
}

function DangerZone({ workspace }: { workspace: Workspace }) {
  const trashDays = useAppFacts()?.trashDays ?? null;
  const [state, action, pending] = useActionState(
    deleteWorkspace.bind(null, workspace.id),
    { error: null },
  );
  return (
    <section
      id="danger"
      className="flex scroll-mt-6 flex-col gap-5 rounded-2xl border border-danger/40 p-5"
    >
      <h2 className="font-display text-base font-semibold text-danger">
        Danger zone
      </h2>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="max-w-md">
          <p className="text-sm font-medium">Archive this workspace</p>
          <p className="text-sm text-ink-2">
            Hides it from the sidebar. Nothing is deleted; restore it from
            Settings → Server &amp; backup.
          </p>
        </div>
        <form action={archiveWorkspace.bind(null, workspace.id)}>
          <Button type="submit">Archive</Button>
        </form>
      </div>
      <form action={action} className="flex flex-col gap-3">
        <div className="max-w-md">
          <p className="text-sm font-medium">Delete this workspace</p>
          <p className="text-sm text-ink-2">
            Moves its folder, tasks and chats to the trash.{" "}
            {trashDays === null
              ? "You can restore it from the trash until it is emptied."
              : `You can restore it for ${String(trashDays)} days; after that it is removed for good.`}
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <Field label={`Type ${workspace.id} to confirm`}>
            <Input
              name="confirm"
              autoComplete="off"
              spellCheck={false}
              className="w-64"
            />
          </Field>
          <Button type="submit" variant="danger" disabled={pending}>
            Delete
          </Button>
        </div>
        <FormStatus error={state.error} />
      </form>
    </section>
  );
}

/** The picture on the workspace's tile. Its own buttons (not the form's Save):
 * the file goes up the moment Upload is clicked, like the Autonomy table. */
function IconRow({ workspace }: { workspace: Workspace }) {
  const file = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<FormState>({ error: null });
  const [busy, start] = useTransition();
  const run = (action: () => Promise<FormState>) => {
    setStatus({ error: null });
    start(async () => {
      const done = await action();
      setStatus(done);
      if (!done.error && file.current) file.current.value = "";
    });
  };
  return (
    <Field
      label="Icon"
      hint="A PNG, JPEG, WebP or SVG picture, up to 1 MB. Without one, the tile shows the first letter of the name."
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          aria-hidden
          style={tileVars(workspace.id)}
          className={cn(
            TILE_BG,
            "grid size-10 shrink-0 place-items-center overflow-hidden rounded-14 font-display text-15 font-semibold uppercase",
          )}
        >
          <WorkspaceTile workspace={workspace} />
        </span>
        <Input
          ref={file}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/svg+xml"
          aria-label="Icon file"
          className="w-auto min-w-0 flex-1 py-1.5 text-ink-2 file:mr-3 file:text-ink"
        />
        <Button
          type="button"
          disabled={busy}
          onClick={() => {
            const picked = file.current?.files?.[0];
            if (!picked) {
              setStatus({ error: "Choose a picture first." });
              return;
            }
            const form = new FormData();
            form.set("icon", picked);
            run(() => uploadWorkspaceIcon(workspace.id, form));
          }}
        >
          {busy ? "Saving…" : "Upload"}
        </Button>
        {workspace.icon && (
          <Button
            type="button"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              run(() => removeWorkspaceIcon(workspace.id));
            }}
          >
            Remove
          </Button>
        )}
      </div>
      <FormStatus
        error={status.error}
        saved={status.saved}
        savedText="Icon saved."
      />
    </Field>
  );
}

function Group({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="flex flex-col gap-4">
      <legend className="mb-4">
        <span className="font-display text-base font-semibold">{title}</span>
        {description && (
          <span className="mt-1 block text-sm text-ink-2">{description}</span>
        )}
      </legend>
      {children}
    </fieldset>
  );
}
