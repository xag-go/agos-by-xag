"use client";

import type { ModelSelection } from "@agos/core";
import { useActionState, useState } from "react";
import type { CatalogProvider, KanbanBoard } from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { DialogCloseButton, RouteDialog } from "@/shared/ui/dialog";
import { Field, Input, Select, Textarea } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Switch } from "@/shared/ui/switch";
import { createCard } from "./card-actions";
import { kanbanStatusLabel } from "./kanban-columns";

/** A new card on the workspace's Kanban (Hermes's own Kanban). */
export function NewCardModal({
  workspaceId,
  board,
  catalog,
  defaultModel,
  skills = [],
  closeHref,
}: {
  workspaceId: string;
  board: KanbanBoard;
  catalog: CatalogProvider[];
  defaultModel: ModelSelection;
  /** The workspace's own skills: picked ones are loaded for the worker, their versions pinned. */
  skills?: string[];
  closeHref: string;
}) {
  const [state, action, pending] = useActionState(
    createCard.bind(null, workspaceId),
    { error: null },
  );
  const [ownModel, setOwnModel] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const open = board.cards.filter(
    (c) => c.status !== "done" && c.status !== "archived",
  );
  return (
    <RouteDialog closeHref={closeHref} label="New card" size="md">
      <form action={action} className="flex max-h-[92dvh] flex-col">
        <header className="flex items-start gap-3 border-b border-line px-5 py-4">
          <div className="flex-1">
            <h2 className="font-display text-xl font-semibold">New card</h2>
            <p className="mt-0.5 text-sm text-ink-2">
              Given to a member, it starts by itself. With nobody, it goes to
              Triage: Hermes fleshes it out and gives it to the team.
            </p>
          </div>
          <DialogCloseButton />
        </header>

        <div className="flex flex-col gap-4 overflow-y-auto px-5 py-5">
          <Field label="Title">
            <Input name="title" required maxLength={200} />
          </Field>
          <Field
            label="Description"
            hint="What you want done: everything the member needs to do it alone."
          >
            <Textarea name="body" rows={5} />
          </Field>
          <Field
            label="Success criteria"
            hint="One per line. Added to the description; goal mode checks the work against them."
          >
            <Textarea name="criteria" rows={3} />
          </Field>
          {skills.length > 0 && (
            <fieldset className="flex flex-col gap-1.5">
              <legend className="text-sm font-medium text-ink">
                Load skills
              </legend>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {skills.map((name) => (
                  <label
                    key={name}
                    className="flex items-center gap-1.5 text-sm"
                  >
                    <input type="checkbox" name="skills" value={name} />
                    <span className="font-mono text-xs">{name}</span>
                  </label>
                ))}
              </div>
              <span className="text-xs text-ink-3">
                Hermes loads them for the member; the card keeps their versions.
              </span>
            </fieldset>
          )}
          <Field label="Member">
            <Select name="member" defaultValue="">
              <option value="">Nobody yet (Triage)</option>
              {board.members.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.title}
                </option>
              ))}
            </Select>
          </Field>

          <div className="rounded-xl border border-line px-4 py-3">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <p className="text-sm font-medium text-ink">Its own model</p>
                <p className="mt-0.5 text-xs text-ink-3">
                  Off: the member&apos;s own model.
                </p>
              </div>
              <Switch
                defaultOn={false}
                label="Its own model"
                name="ownModel"
                onChange={setOwnModel}
              />
            </div>
            {ownModel && (
              <div className="mt-3">
                <ModelPicker catalog={catalog} initial={defaultModel} />
              </div>
            )}
          </div>

          <div className="rounded-xl border border-line px-4 py-3">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <p className="text-sm font-medium text-ink">Goal mode</p>
                <p className="mt-0.5 text-xs text-ink-3">
                  The member keeps going until a judge agrees the card is done
                  (title, description, success criteria): Hermes&apos;s own goal
                  mode.
                </p>
              </div>
              <Switch defaultOn={false} label="Goal mode" name="goal" />
            </div>
          </div>

          <div className="rounded-xl border border-line px-4 py-3">
            <p className="text-sm font-medium text-ink">Starts after</p>
            <p className="mt-0.5 text-xs text-ink-3">
              It waits in To do and starts by itself once these cards are done.
            </p>
            {picked.map((id) => (
              <input key={id} type="hidden" name="parents" value={id} />
            ))}
            {open.length === 0 ? (
              <p className="mt-2 text-xs text-ink-3">No other open card yet.</p>
            ) : (
              <ul className="mt-2 flex max-h-44 flex-col gap-0.5 overflow-y-auto">
                {open.map((c) => {
                  const on = picked.includes(c.id);
                  return (
                    <li key={c.id}>
                      <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm hover:bg-sunken">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => {
                            setPicked(
                              on
                                ? picked.filter((p) => p !== c.id)
                                : [...picked, c.id],
                            );
                          }}
                          className="size-4 accent-accent"
                        />
                        <span className="min-w-0 flex-1 truncate text-ink">
                          {c.title}
                        </span>
                        <span className="text-xs text-ink-3">
                          {kanbanStatusLabel(c.status, c.statusLabel)}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <footer className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 max-md:pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <FormStatus error={state.error} className="mr-auto" />
          <Button
            type="submit"
            variant="primary"
            className="ml-auto max-md:!h-11"
            disabled={pending}
          >
            {pending ? "Creating…" : "Create card"}
          </Button>
        </footer>
      </form>
    </RouteDialog>
  );
}
