"use client";

import type { ModelSelection } from "@agos/core";
import { useState, useTransition } from "react";
import type {
  CatalogProvider,
  ImportPreview,
  ImportReport,
} from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { Field, Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { importBundle, previewBundle, type Strategies } from "./actions";
import {
  DEFAULT_STRATEGIES,
  fileBase64,
  ImportReportView,
  InputFields,
  missingInputs,
  StrategyFields,
} from "./import-fields";
import { Panel } from "@/shared/ui/panel";

/**
 * Import a bundle (a zip another AGOS exported, or a ready-made team's): its
 * preview first (what it holds, what this workspace has already, the trust
 * level), then what to do on each collision, the keys it asks for, and the
 * fidelity report once it is in. `workspaceId` null: into a new workspace.
 */
export function ImportPanel({
  workspaceId,
  catalog = [],
  defaultModel = null,
}: {
  workspaceId: string | null;
  catalog?: CatalogProvider[];
  defaultModel?: ModelSelection | null;
}) {
  const [data, setData] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [strategies, setStrategies] = useState<Strategies>(DEFAULT_STRATEGIES);
  const [values, setValues] = useState<Record<string, string>>({});
  const [later, setLater] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [model, setModel] = useState<ModelSelection | null>(defaultModel);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  if (report) {
    return (
      <div className="flex flex-col gap-3">
        <ImportReportView report={report} openLink={workspaceId === null} />
        <div>
          <Button
            onClick={() => {
              setReport(null);
              setPreview(null);
              setData(null);
              setValues({});
            }}
          >
            Import another
          </Button>
        </div>
      </div>
    );
  }

  const missing = preview ? missingInputs(preview.inputs, values, later) : [];
  const collisions = preview
    ? [
        ...preview.agents.filter((a) => a.exists).map(() => "agents" as const),
        ...preview.skills.filter((s) => s.exists).map(() => "skills" as const),
        ...preview.automations
          .filter((a) => a.exists)
          .map(() => "automations" as const),
        ...(preview.visionExists ? ["vision" as const] : []),
      ]
    : [];
  const kinds = [...new Set(collisions)];

  return (
    <div className="flex flex-col gap-4">
      <Field
        label="Bundle (.zip)"
        hint="A workspace AGOS exported: TEAM.md, agents, skills, automations, vision.md."
      >
        <Input
          type="file"
          accept=".zip,application/zip"
          className="pt-1.5"
          onChange={(e) => {
            const file = e.target.files?.[0];
            setError(null);
            setPreview(null);
            if (!file) return;
            start(async () => {
              const encoded = await fileBase64(file);
              const r = await previewBundle(encoded, workspaceId);
              if (r.error || !r.preview) {
                setError(r.error ?? "That bundle couldn't be read.");
                return;
              }
              setData(encoded);
              setPreview(r.preview);
              setName(r.preview.name);
            });
          }}
        />
      </Field>
      {preview && (
        <Panel className="flex flex-col gap-4 p-4">
          <div>
            <p className="font-display text-base font-semibold">
              {preview.name || "Bundle"}
            </p>
            {preview.description && (
              <p className="text-sm text-ink-2">{preview.description}</p>
            )}
            <p className="mt-1 text-xs text-ink-3">
              {preview.agents.length} members · {preview.skills.length} skills ·{" "}
              {preview.automations.length} automations
              {preview.vision ? " · a Vision" : ""}
              {preview.trust === "scripts"
                ? " · has scripts its skills may run in the sandbox"
                : " · text only"}
            </p>
          </div>
          <ul className="flex flex-col gap-0.5 text-sm">
            {preview.agents.map((a) => (
              <li key={a.name}>
                <span className="font-medium">{a.title}</span>{" "}
                <span className="text-ink-3">
                  @{a.name}
                  {a.reportsTo ? ` → @${a.reportsTo}` : ""}
                  {a.exists ? " · this workspace has one" : ""}
                </span>
              </li>
            ))}
          </ul>
          {workspaceId === null && (
            <div className="flex flex-col gap-3">
              <Field label="New workspace's name">
                <Input
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                  }}
                />
              </Field>
              {defaultModel && (
                <ModelPicker
                  catalog={catalog}
                  initial={defaultModel}
                  name="import-model"
                  onChange={setModel}
                />
              )}
            </div>
          )}
          {kinds.length > 0 && (
            <StrategyFields
              value={strategies}
              onChange={setStrategies}
              kinds={kinds}
            />
          )}
          <InputFields
            inputs={preview.inputs}
            values={values}
            later={later}
            onValues={setValues}
            onLater={setLater}
          />
          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              disabled={busy || missing.length > 0 || data === null}
              onClick={() => {
                if (data === null) return;
                setError(null);
                start(async () => {
                  const r = await importBundle(data, {
                    workspaceId,
                    name,
                    defaultModel: model,
                    strategies,
                    inputs: values,
                    later,
                  });
                  if (r.error || !r.report)
                    setError(r.error ?? "Not imported.");
                  else setReport(r.report);
                });
              }}
            >
              {busy ? "Importing…" : "Import"}
            </Button>
            {missing.length > 0 && (
              <span className="text-xs text-ink-3">
                Fill in or mark for later: {missing.join(", ")}
              </span>
            )}
          </div>
        </Panel>
      )}
      <FormStatus error={error} />
    </div>
  );
}
