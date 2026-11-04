"use client";

import { useActionState, useState, useTransition } from "react";
import {
  createLabel,
  deleteLabel,
  renameLabelFolder,
  updateLabel,
} from "@/features/kanban/board-actions";
import {
  LABEL_COLORS,
  labelClass,
  type BoardLabel,
} from "@/features/kanban/labels";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input, Select } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { Panel, PanelSection } from "@/shared/ui/panel";

/** Workspace settings → Labels: the card labels (name, colour) grouped in folders.
 * Cards carry them in their Hermes body; the Kanban filters and groups by them and
 * the agents put them on with their agos_label tool. */
export function LabelsSettings({
  workspaceId,
  labels,
}: {
  workspaceId: string;
  labels: BoardLabel[];
}) {
  const [state, create, creating] = useActionState(
    createLabel.bind(null, workspaceId),
    { error: null },
  );
  const folders = [...new Set(labels.map((l) => l.folder ?? ""))].sort(
    (a, b) => (a === "" ? 1 : b === "" ? -1 : a.localeCompare(b)),
  );
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <p className="text-sm text-ink-2">
        Labels mark cards on the Kanban (filter and group by them, or put them
        on many cards at once). A folder groups labels. The team can use them
        too.
      </p>
      <Panel
        as="form"
        action={create}
        className="flex flex-wrap items-end gap-3 p-5"
      >
        <Field label="New label" className="w-48">
          <Input name="name" required maxLength={40} placeholder="Urgent" />
        </Field>
        <Field label="Colour" className="w-32">
          <Select name="color" defaultValue="gray">
            {LABEL_COLORS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Folder (optional)" className="w-48">
          <Input
            name="folder"
            maxLength={40}
            placeholder="Channels"
            list="label-folders"
          />
        </Field>
        <datalist id="label-folders">
          {folders.filter(Boolean).map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
        <Button type="submit" variant="primary" disabled={creating}>
          {creating ? "Adding…" : "Add label"}
        </Button>
        <FormStatus error={state.error} />
      </Panel>
      {labels.length === 0 && (
        <p className="text-sm text-ink-3">No labels yet.</p>
      )}
      {folders.map((folder) => (
        <Folder
          key={folder || "none"}
          workspaceId={workspaceId}
          folder={folder}
          labels={labels.filter((l) => (l.folder ?? "") === folder)}
          folders={folders}
        />
      ))}
    </div>
  );
}

function Folder({
  workspaceId,
  folder,
  labels,
  folders,
}: {
  workspaceId: string;
  folder: string;
  labels: BoardLabel[];
  folders: string[];
}) {
  const [busy, start] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const run = (task: () => Promise<{ error: string | null }>) => {
    start(async () => {
      setError((await task()).error);
    });
  };
  return (
    <PanelSection className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-2">
        {renaming === null ? (
          <>
            <h2 className="font-display text-base font-semibold">
              {folder || "No folder"}
            </h2>
            {folder && (
              <Button
                variant="ghost"
                onClick={() => {
                  setRenaming(folder);
                }}
              >
                Rename folder
              </Button>
            )}
          </>
        ) : (
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                const r = await renameLabelFolder(
                  workspaceId,
                  folder,
                  renaming,
                );
                if (!r.error) setRenaming(null);
                return r;
              });
            }}
          >
            <Input
              aria-label="Folder name"
              className="w-48"
              value={renaming}
              maxLength={40}
              onChange={(e) => {
                setRenaming(e.target.value);
              }}
            />
            <Button type="submit" variant="primary" disabled={busy}>
              Save
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setRenaming(null);
              }}
            >
              Cancel
            </Button>
          </form>
        )}
      </div>
      <ul className="flex flex-col gap-2">
        {labels.map((l) => (
          <LabelRow
            key={l.id}
            label={l}
            folders={folders}
            busy={busy}
            onChange={(patch) => {
              run(() => updateLabel(workspaceId, l.id, patch));
            }}
            onDelete={() => {
              run(() => deleteLabel(workspaceId, l.id));
            }}
          />
        ))}
      </ul>
      <FormStatus error={error} />
    </PanelSection>
  );
}

function LabelRow({
  label,
  folders,
  busy,
  onChange,
  onDelete,
}: {
  label: BoardLabel;
  folders: string[];
  busy: boolean;
  onChange: (patch: { name?: string; color?: string; folder?: string }) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(label.name);
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="flex flex-wrap items-center gap-2">
      <span
        className={cn(
          "w-28 truncate rounded-md px-1.5 py-0.5 text-xs",
          labelClass(label.color),
        )}
      >
        {label.name}
      </span>
      <Input
        aria-label={`Name of ${label.name}`}
        className="w-44"
        value={name}
        maxLength={40}
        onChange={(e) => {
          setName(e.target.value);
        }}
        onBlur={() => {
          if (name.trim() && name.trim() !== label.name)
            onChange({ name: name.trim() });
        }}
      />
      <Select
        aria-label={`Colour of ${label.name}`}
        className="w-28"
        value={label.color}
        disabled={busy}
        onChange={(e) => {
          onChange({ color: e.target.value });
        }}
      >
        {LABEL_COLORS.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </Select>
      <Select
        aria-label={`Folder of ${label.name}`}
        className="w-36"
        value={label.folder ?? ""}
        disabled={busy}
        onChange={(e) => {
          onChange({ folder: e.target.value });
        }}
      >
        <option value="">No folder</option>
        {folders.filter(Boolean).map((f) => (
          <option key={f} value={f}>
            {f}
          </option>
        ))}
      </Select>
      {confirming ? (
        <>
          <span className="text-sm text-ink-2">
            Remove it from every card too?
          </span>
          <Button variant="danger" disabled={busy} onClick={onDelete}>
            Delete
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setConfirming(false);
            }}
          >
            Keep
          </Button>
        </>
      ) : (
        <Button
          variant="ghost"
          onClick={() => {
            setConfirming(true);
          }}
        >
          Delete
        </Button>
      )}
    </li>
  );
}
