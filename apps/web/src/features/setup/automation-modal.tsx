"use client";

import type { ModelSelection } from "@agos/core";
import { useActionState, useRef } from "react";
import type {
  Automation,
  AutomationRevision,
  CatalogProvider,
  LibraryItem,
  TicketPreset,
} from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { DialogCloseButton, RouteDialog } from "@/shared/ui/dialog";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { Switch } from "@/shared/ui/switch";
import { Tabs } from "@/shared/ui/tabs";
import { saveAutomation } from "./actions";
import { AutomationFooter } from "./automation-footer";
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
  const title = automation ? "Edit automation" : "New automation";
  const formRef = useRef<HTMLFormElement>(null);

  return (
    <RouteDialog closeHref={closeHref} label={title} size="md">
      <form
        ref={formRef}
        action={action}
        className="flex max-h-[92dvh] flex-col"
      >
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

        <AutomationFooter
          workspaceId={workspaceId}
          automation={automation}
          pending={pending}
          saveError={state.error}
          form={formRef}
        />
      </form>
    </RouteDialog>
  );
}
