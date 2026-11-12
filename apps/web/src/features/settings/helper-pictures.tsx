"use client";

import { useState, useTransition } from "react";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { shownValue } from "./hermes-settings-shared";
import { saveHermesHelperModels } from "./preferences-actions";
import {
  asText,
  type Choice,
  type Confirm,
  type Field,
  where,
} from "./helper-models-shared";
import { Details, RawFields } from "./helper-fields";
import { PanelSection } from "@/shared/ui/panel";

/** How a picture the owner sends reaches the model: Hermes's modes in plain words. */
export function PicturesCard({
  field,
  choices,
  confirm,
}: {
  field: Field;
  choices: Choice[];
  confirm: Confirm;
}) {
  const start = asText(field.value);
  const [value, setValue] = useState(start);
  const [note, setNote] = useState<string | null>(null);
  const [saving, startSave] = useTransition();
  const shown = choices.some((c) => c.value === start)
    ? choices
    : [{ value: start, label: start || "Not set", hint: "" }, ...choices];

  return (
    <PanelSection className="p-5">
      <h3 className="font-medium">Pictures you send</h3>
      <p className="mt-1 text-sm text-ink-2">
        What happens to a picture you send to an agent.
      </p>
      <div
        role="radiogroup"
        aria-label="Pictures you send"
        className="mt-3 flex flex-col gap-2"
      >
        {shown.map((c) => (
          <label
            key={c.value}
            className={cn(
              "flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-2.5 text-sm",
              value === c.value ? "border-ink" : "border-line",
            )}
          >
            <input
              type="radio"
              name="image-mode"
              className="mt-1"
              checked={value === c.value}
              disabled={saving}
              onChange={() => {
                setValue(c.value);
                setNote(null);
              }}
            />
            <span>
              <span className="block font-medium">
                {c.label}
                {c.value === asText(field.hermesDefault) && (
                  <span className="font-normal text-ink-3"> · the default</span>
                )}
              </span>
              {c.hint && <span className="block text-ink-2">{c.hint}</span>}
            </span>
          </label>
        ))}
      </div>
      {field.spread.length > 0 && (
        <p className="mt-2 text-sm text-warn">
          Workspaces differ:{" "}
          {field.spread
            .map(
              (s) =>
                `${s.profiles.join(", ")}: ${choices.find((c) => c.value === s.value)?.label ?? shownValue(s.value)}`,
            )
            .join("; ")}
          . Saving sets it the same everywhere.
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          className="h-8"
          disabled={saving || (value === start && field.spread.length === 0)}
          onClick={() => {
            startSave(async () => {
              const back =
                value === asText(field.hermesDefault) && field.managed;
              const r = back
                ? await saveHermesHelperModels({}, [field.key])
                : await saveHermesHelperModels({ [field.key]: value }, []);
              setNote(r.error ?? "Saved.");
            });
          }}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
        {note && (
          <span role="status" className="text-sm text-ink-2">
            {note}
          </span>
        )}
      </div>
      <Details title={field.key} description={field.description}>
        <p className="text-xs text-ink-2">
          In use: {shownValue(field.value)} · {where(field)} · the default:{" "}
          {shownValue(field.hermesDefault)}
        </p>
        {field.managed && (
          <RawFields fields={[field]} confirm={confirm} resetOnly />
        )}
      </Details>
    </PanelSection>
  );
}
