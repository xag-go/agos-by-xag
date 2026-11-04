"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import type {
  HermesAllSettings as HermesSettings,
  HermesSettingRow as HermesSetting,
} from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import { Field, Input, Select } from "@/shared/ui/field";
import {
  changedFromDefault,
  matches,
  type Show,
  type Workspace,
} from "./hermes-settings-shared";
import { SettingRow, SharedHome } from "./hermes-setting-row";
import { EditModelPair } from "./hermes-edit-model-pair";
import { EditSetting } from "./hermes-edit-setting";
import { Panel } from "@/shared/ui/panel";

/** Every Hermes setting, grouped, searchable; Hermes's own list and words. */
export function HermesSettingsPage({
  data,
  workspaces,
  catalog = [],
}: {
  data: HermesSettings;
  workspaces: Workspace[];
  catalog?: CatalogProvider[];
}) {
  const params = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [show, setShow] = useState<Show>("all");
  const [editing, setEditing] = useState<HermesSetting | null>(null);
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const firstWs = workspaces[0]?.id ?? null;

  const groups = useMemo(() => {
    const rows = data.settings.filter(
      (r) =>
        matches(r, words) &&
        (show === "all" ||
          (show === "changed" && changedFromDefault(r)) ||
          (show === "agos" && r.rule !== null && r.rule.kind !== "secret") ||
          (show === "differ" && !r.same)),
    );
    return data.groups.map((name) => ({
      name,
      rows: rows.filter((r) => r.group === name),
      total: data.settings.filter((r) => r.group === name).length,
    }));
  }, [data, words, show]);
  const found = groups.reduce((n, g) => n + g.rows.length, 0);

  return (
    <div className="flex max-w-5xl flex-col gap-5">
      <p className="text-sm text-ink-2">
        {data.settings.length} settings, read from {data.workspaces} workspace
        {data.workspaces === 1 ? "" : "s"} ({data.profiles} Hermes profiles:
        each Co-Founder and member). The list, the descriptions and the defaults
        are Hermes&apos;s own, so a setting a Hermes update adds shows here by
        itself. The “Hermes .env” group lists Hermes&apos;s own .env settings
        (secrets stay hidden); where a .env line and config.yaml set the same
        thing, the row says which one Hermes really uses. Settings marked “Set
        by AGOS” are written by AGOS on every sync; the reason is under each
        one. “Your choice” settings start on AGOS&apos;s recommended value and
        are yours to change. The Co-Founder can show and change these from a
        chat too, with Undo on its card.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Search" className="min-w-64 flex-1">
          <Input
            type="search"
            value={query}
            placeholder="e.g. approvals, memory, kanban dispatch, blocklist"
            onChange={(e) => {
              setQuery(e.target.value);
            }}
          />
        </Field>
        <Field label="Show" className="w-60">
          <Select
            value={show}
            onChange={(e) => {
              setShow(e.target.value as Show);
            }}
          >
            <option value="all">Every setting</option>
            <option value="changed">Not Hermes&apos;s default</option>
            <option value="differ">Different between workspaces</option>
            <option value="agos">Set or changed by AGOS</option>
          </Select>
        </Field>
      </div>
      <p role="status" className="text-xs text-ink-3">
        {found} shown
      </p>
      {groups.map((group) =>
        group.rows.length === 0 ? null : (
          <Panel
            as="details"
            key={group.name}
            open={
              group.name !== "Not used by AGOS" ||
              words.length > 0 ||
              show !== "all"
            }
          >
            <summary className="cursor-pointer px-5 py-4">
              <span className="font-medium">{group.name}</span>
              <span className="ml-2 text-sm text-ink-3">
                {group.rows.length === group.total
                  ? group.total
                  : `${group.rows.length} of ${group.total}`}
              </span>
              {group.name === "Not used by AGOS" ? (
                <span className="mt-1 block text-sm text-ink-2">
                  {data.notUsedWhy}
                </span>
              ) : null}
            </summary>
            <ul className="divide-y divide-line border-t border-line">
              {group.rows.map((row) => (
                <SettingRow
                  key={row.key}
                  row={row}
                  cards={data.cards}
                  firstWs={firstWs}
                  onEdit={() => {
                    setEditing(row);
                  }}
                />
              ))}
            </ul>
          </Panel>
        ),
      )}
      <SharedHome home={data.sharedHome} rows={data.shared} />
      {editing?.pair ? (
        <EditModelPair
          pair={editing.pair}
          rows={data.settings}
          catalog={catalog}
          workspaces={workspaces}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : editing ? (
        <EditSetting
          row={editing}
          workspaces={workspaces}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

/** A line under a Hermes card: the same settings, with every other one. */
export function AllHermesSettingsLink({ search }: { search: string }) {
  return (
    <p className="mt-4 text-sm text-ink-2">
      <Link
        href={`/settings/hermes?q=${encodeURIComponent(search)}`}
        className="underline"
      >
        See these and every other Hermes setting
      </Link>
    </p>
  );
}
