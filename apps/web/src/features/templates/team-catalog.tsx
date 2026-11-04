"use client";

import type { ModelSelection } from "@agos/core";
import { useEffect, useState, useTransition } from "react";
import type { CatalogProvider, CatalogTeam, ImportReport } from "@/data/types";
import { ModelPicker } from "@/features/models/model-picker";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { Field, Input } from "@/shared/ui/field";
import { FormStatus } from "@/shared/ui/form-status";
import { installTemplate, listTemplates } from "./actions";
import {
  DEFAULT_STRATEGIES,
  ImportReportView,
  InputFields,
  missingInputs,
} from "./import-fields";
import { Panel } from "@/shared/ui/panel";

/**
 * The ready-made teams: pick one, see its org chart, skills and automations,
 * then install it as a new workspace (its name and model). Installing is an
 * import: every member, skill and automation is made the normal way.
 */
export function TeamCatalog({
  catalog = [],
  defaultModel = null,
}: {
  catalog?: CatalogProvider[];
  defaultModel?: ModelSelection | null;
}) {
  const [teams, setTeams] = useState<CatalogTeam[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [model, setModel] = useState<ModelSelection | null>(defaultModel);
  const [values, setValues] = useState<Record<string, string>>({});
  const [later, setLater] = useState<string[]>([]);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();

  useEffect(() => {
    void listTemplates().then((r) => {
      if (r.error) setError(r.error);
      else setTeams(r.teams ?? []);
    });
  }, []);

  if (report) return <ImportReportView report={report} openLink />;
  if (teams === null)
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-ink-3">Loading the teams…</p>
        <FormStatus error={error} />
      </div>
    );
  const team = teams.find((t) => t.slug === picked) ?? null;
  const missing = team ? missingInputs(team.inputs, values, later) : [];

  return (
    <div className="flex flex-col gap-4">
      <ul className="grid gap-3 sm:grid-cols-2">
        {teams.map((t) => (
          <li key={t.slug}>
            <button
              type="button"
              aria-pressed={t.slug === picked}
              onClick={() => {
                setPicked(t.slug);
                setName(t.name);
                setValues({});
                setLater([]);
              }}
              className={cn(
                "flex h-full w-full flex-col gap-1 rounded-2xl border p-4 text-left",
                t.slug === picked
                  ? "border-accent bg-accent-soft"
                  : "border-line bg-panel hover:border-ink-3",
              )}
            >
              <span className="font-display text-base font-semibold">
                {t.name}
              </span>
              <span className="text-sm text-ink-2">{t.description}</span>
              <span className="text-xs text-ink-3">
                {t.agents.length} members · {t.skills.length} skills ·{" "}
                {t.automations.length} automations
              </span>
            </button>
          </li>
        ))}
      </ul>
      {team && (
        <Panel className="flex flex-col gap-4 p-4">
          <ul className="flex flex-col gap-0.5 text-sm">
            {team.agents.map((a) => (
              <li key={a.name} className={a.reportsTo ? "pl-5" : ""}>
                <span className="font-medium">{a.title}</span>{" "}
                <span className="text-ink-3">— {a.summary}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-3">
            Skills: {team.skills.join(", ")}. Automations (installed off):{" "}
            {team.automations.map((a) => a.name).join(", ")}.
          </p>
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
                name="template-model"
                onChange={setModel}
              />
            )}
          </div>
          <InputFields
            inputs={team.inputs}
            values={values}
            later={later}
            onValues={setValues}
            onLater={setLater}
          />
          <div className="flex items-center gap-3">
            <Button
              variant="primary"
              disabled={busy || missing.length > 0}
              onClick={() => {
                setError(null);
                start(async () => {
                  const r = await installTemplate(team.slug, {
                    workspaceId: null,
                    name,
                    defaultModel: model,
                    strategies: DEFAULT_STRATEGIES,
                    inputs: values,
                    later,
                  });
                  if (r.error || !r.report)
                    setError(r.error ?? "Not installed.");
                  else setReport(r.report);
                });
              }}
            >
              {busy ? "Installing…" : "Create the workspace"}
            </Button>
          </div>
        </Panel>
      )}
      <FormStatus error={error} />
    </div>
  );
}
