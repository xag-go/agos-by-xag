"use client";

import type { ModelSelection } from "@agos/core";
// The zod-free entry: the browser gets the id rule without zod.
import {
  WORKSPACE_ID_PATTERN,
  workspaceIdFromName,
} from "@agos/core/workspace-id";
import { useActionState, useState } from "react";
import type { CatalogProvider } from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { Field, Input, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { createWorkspace } from "./actions";

export function NewWorkspaceForm({
  catalog,
  defaultModel,
}: {
  catalog: CatalogProvider[];
  defaultModel: ModelSelection;
}) {
  const [name, setName] = useState("");
  const [state, action, pending] = useActionState(createWorkspace, {
    error: null,
  });
  const id = workspaceIdFromName(name);
  const idValid = WORKSPACE_ID_PATTERN.test(id);

  return (
    <form action={action} className="flex max-w-2xl flex-col gap-8">
      <div className="flex flex-col gap-4">
        <Field label="Name">
          <Input
            name="name"
            required
            value={name}
            onChange={(e) => {
              setName(e.target.value);
            }}
            placeholder="e.g. Investor"
          />
        </Field>
        <p className="-mt-2 text-xs text-ink-3">
          Folder name:{" "}
          {name === "" ? (
            "set from the name"
          ) : idValid ? (
            <span className="font-medium text-ink-2">{id}</span>
          ) : (
            <span className="text-danger">
              use at least one letter or digit
            </span>
          )}{" "}
          — fixed once created (a number is added if it&apos;s taken). You can
          rename the workspace later.
        </p>
        <Field
          label="Description"
          hint="Helps the agent understand what this workspace is for."
        >
          <Textarea name="description" rows={3} />
        </Field>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-3">
          <span className="font-display text-base font-semibold">
            Default model
          </span>
          <span className="mt-1 block text-sm text-ink-2">
            Tasks and chats start with this. You can change it per task, per
            chat, or later in workspace settings.
          </span>
        </legend>
        <ModelPicker catalog={catalog} initial={defaultModel} />
      </fieldset>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-3">
          <span className="font-display text-base font-semibold">Telegram</span>
          <span className="mt-1 block text-sm text-ink-2">
            Optional. The workspace gets its own bot: you scan a QR code and tap
            “Create bot” in Telegram, nothing to copy. You talk to the
            Co-Founder there.
          </span>
        </legend>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            name="telegramBot"
            className="size-4 accent-majorelle"
          />
          Create a Telegram bot for this workspace (next step)
        </label>
      </fieldset>

      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" disabled={!idValid || pending}>
          {pending ? "Creating…" : "Create workspace"}
        </Button>
        <FormStatus error={state.error} />
      </div>
    </form>
  );
}
