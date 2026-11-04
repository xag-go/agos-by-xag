"use client";

import type { ModelSelection } from "@agos/core";
import { useActionState, useTransition } from "react";
import type {
  Automation,
  AutomationRevision,
  CatalogProvider,
  LibraryItem,
  TicketPreset,
} from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { DialogCloseButton, RouteDialog } from "@/shared/ui/dialog";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { Switch } from "@/shared/ui/switch";
import { Tabs } from "@/shared/ui/tabs";
import { useAsk } from "@/shared/ui/confirm";
import { FormStatus } from "@/shared/ui/form-status";
import { deleteAutomation, saveAutomation } from "./actions";
import {
  PolicyField,
  RevisionsTab,
  TicketPresetField,
  VariablesField,
} from "./routine-fields";
import { StartField } from "./start-field";
import { WhoField } from "./who-field";

/** Create a new automation, or edit one when `automation` is given. */
export function AutomationModal({
  workspaceId,
  automation,
  catalog,
  defaultModel,
  closeHref,
  agents,
  revisions = [],
  presets = [],
}: {
  workspaceId: string;
  automation: Automation | null;
  catalog: CatalogProvider[];
  defaultModel: ModelSelection;
  closeHref: string;
  agents: LibraryItem[];
  /** The Revisions tab (editing only): every saved version, read once with the page. */
  revisions?: AutomationRevision[];
  /** The Tickets tab's presets (Linear / Jira / Asana / GitHub). */
  presets?: TicketPreset[];
}) {
  const [state, action, pending] = useActionState(
    saveAutomation.bind(null, workspaceId, automation?.id ?? null),
    { error: null },
  );
  const editing = automation !== null;
  const { dialog, confirm } = useAsk();
  const [deleting, startDelete] = useTransition();
  const title = editing ? "Edit automation" : "New automation";

  return (
    <RouteDialog closeHref={closeHref} label={title} size="md">
      {dialog}
      <form action={action} className="flex max-h-[92dvh] flex-col">
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="flex-1">
            <h2 className="font-display text-xl font-semibold">{title}</h2>
            <p className="mt-0.5 text-sm text-ink-2">
              Starts on its schedule or the moment something happens in another
              app, done by the member (or the team) you pick below. It runs by
              itself to the end and reports back here and to your Co-Founder
              chat.
            </p>
          </div>
          <DialogCloseButton />
        </header>

        <Tabs
          items={[
            {
              id: "setup",
              label: "Setup",
              content: (
                <div className="flex flex-col gap-5">
                  <Field label="Name">
                    <Input
                      name="name"
                      required
                      defaultValue={automation?.name}
                      placeholder="e.g. Daily store brief"
                    />
                  </Field>
                  <Field
                    label="What to do"
                    hint="Saved as a readable file in this workspace, so you can also edit it there."
                  >
                    <Textarea
                      name="instructions"
                      required
                      rows={4}
                      defaultValue={automation?.instructions}
                      placeholder="e.g. Summarise yesterday's orders and flag anything unusual."
                    />
                  </Field>
                  <WhoField automation={automation} agents={agents} />
                  <StartField
                    workspaceId={workspaceId}
                    schedule={automation?.schedule}
                    scheduleDisplay={automation?.scheduleDisplay ?? null}
                    hook={Boolean(automation?.hook)}
                  />
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium">Check with me first</p>
                      <p className="text-xs text-ink-3">
                        Off: it runs by itself to the end and you get the
                        report. On: nothing starts before you approve it (on the
                        Board).
                      </p>
                    </div>
                    <Switch
                      name="checkFirst"
                      defaultOn={automation?.checkFirst ?? false}
                      label="Check with me first"
                    />
                  </div>
                  <fieldset className="flex flex-col gap-2">
                    <legend className="mb-1.5 text-sm font-medium">
                      Model
                    </legend>
                    <ModelPicker
                      catalog={catalog}
                      initial={automation?.model ?? defaultModel}
                    />
                  </fieldset>
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-sm font-medium">On</p>
                      <p className="text-xs text-ink-3">
                        Off = paused: it doesn&apos;t start until you turn it
                        back on. Nothing is deleted.
                      </p>
                    </div>
                    <Switch
                      name="on"
                      defaultOn={automation?.on ?? true}
                      label="Automation on or off"
                    />
                  </div>
                  <Field
                    label="If a run was missed (server off)"
                    hint="Never more than one run, and never one missed while it was off or more than 7 days ago."
                  >
                    <Select
                      name="catchUp"
                      defaultValue={automation?.catchUp ?? "once"}
                    >
                      <option value="once">
                        Run it once when AGOS is back
                      </option>
                      <option value="skip">Skip it</option>
                    </Select>
                  </Field>
                </div>
              ),
            },
            {
              id: "variables",
              label: "Variables",
              count: automation?.variables?.length ?? 0,
              content: <VariablesField automation={automation} />,
            },
            {
              id: "policy",
              label: "Policy",
              content: <PolicyField automation={automation} />,
            },
            {
              id: "tickets",
              label: "Tickets",
              content: (
                <TicketPresetField
                  automation={automation}
                  presets={presets}
                  agents={agents}
                />
              ),
            },
            ...(automation
              ? [
                  {
                    id: "revisions",
                    label: "Revisions",
                    count: revisions.length,
                    content: (
                      <RevisionsTab
                        workspaceId={workspaceId}
                        automationId={automation.id}
                        revisions={revisions}
                      />
                    ),
                  },
                ]
              : []),
          ]}
        />

        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          <FormStatus error={state.error} className="mr-auto" />
          {automation && (
            <Button
              type="button"
              variant="ghost"
              disabled={deleting}
              onClick={() => {
                void (async () => {
                  const ok = await confirm({
                    title: "Delete this automation?",
                    body: `“${automation.name}” stops and is removed.`,
                    confirmLabel: "Delete",
                    danger: true,
                  });
                  if (!ok) return;
                  startDelete(async () => {
                    await deleteAutomation(workspaceId, automation.id);
                  });
                })();
              }}
            >
              Delete
            </Button>
          )}
          <Button
            type="submit"
            variant="primary"
            className="ml-auto"
            disabled={pending}
          >
            {editing ? "Save changes" : "Create automation"}
          </Button>
        </footer>
      </form>
    </RouteDialog>
  );
}
