"use client";

import Link from "next/link";
import type { Proposal } from "@/data/types";
import type { Kit } from "@/features/workers/kit-types";
import { KitEditor } from "@/features/workers/kit-editor";
import { KitView } from "@/features/workers/kit-chips";
import { type HireModel, ModelPicker, modelLine } from "../hire-model";
import type { HirePayload } from "../proposal-types";
import { Row } from "./row";
import { Eyebrow } from "@/shared/ui/eyebrow";

export function HireDetails({
  workspaceId,
  forMember = false,
  payload: h,
  serves,
  choices,
  editing,
  onEdit,
}: {
  workspaceId: string;
  /** A kit for a member already on the team: no hire rows (title, goal, role…). */
  forMember?: boolean;
  payload: HirePayload;
  serves: Proposal["serves"];
  /** The models he may pick (Hermes's catalog; null: not known now). */
  choices: Proposal["modelChoices"];
  /** The owner's edited kit and model (null: as proposed). */
  editing: { kit: Kit; model: HireModel } | null;
  /** Edit the kit and model before Approve (absent: read only); null = as proposed. */
  onEdit?: (next: { kit: Kit; model: HireModel } | null) => void;
}) {
  const base = `/w/${encodeURIComponent(workspaceId)}`;
  const proposed: Kit = h.kit ?? {};
  const kit = editing?.kit ?? null;
  const onKit = onEdit
    ? (next: Kit | null) => {
        onEdit(
          next
            ? { kit: next, model: editing ? editing.model : (h.model ?? null) }
            : null,
        );
      }
    : undefined;
  const why = (
    <Row label="Why">
      {h.why ? (
        <span className="whitespace-pre-wrap">{h.why}</span>
      ) : (
        <span className="text-ink-3">not given</span>
      )}
    </Row>
  );
  return (
    <div className="flex flex-col gap-1">
      {forMember ? (
        <>
          <Row label="For">
            <span className="font-medium">@{h.member || "?"}</span>
            <span className="text-ink-3">
              {" "}
              · already on the team; its role, memory and chats stay
            </span>
          </Row>
          {why}
        </>
      ) : (
        <>
          <Row label="Job title">
            <span className="font-medium">{h.title || "—"}</span>
            {h.name && <span className="text-ink-3"> · @{h.name}</span>}
          </Row>
          {why}
        </>
      )}
      {forMember ? null : serves ? (
        <Row label="Serves">
          {serves.title === null || serves.title === undefined ? (
            <span className="text-danger">
              goal #{String(serves.id)} not found
            </span>
          ) : (
            <Link
              href={`${base}/vision`}
              className="underline decoration-line underline-offset-2 hover:decoration-ink"
            >
              <span className="font-medium">{serves.title}</span>
              <span className="text-ink-3">
                {" "}
                · {serves.level === "project" ? "project" : "goal"} #
                {String(serves.id)}
                {serves.status && serves.status !== "active"
                  ? ` (${serves.status})`
                  : ""}
              </span>
            </Link>
          )}
        </Row>
      ) : (
        <Row label="Serves">
          <span className="text-ink-3">no goal named</span>
        </Row>
      )}
      {!forMember && h.role && (
        <Row label="Role">
          <span className="whitespace-pre-wrap">{h.role}</span>
        </Row>
      )}
      {!forMember && (
        <Row label="Reports to">
          {h.reports_to ? `@${h.reports_to}` : "Co-Founder"}
        </Row>
      )}
      {!forMember && (
        <Row label="Skills">
          {h.skills && h.skills.length > 0 ? (
            <span className="flex flex-wrap gap-1">
              {h.skills.map((s) => (
                <span
                  key={s}
                  className="rounded-md bg-sunken px-1.5 py-0.5 font-mono text-xs text-ink-2"
                >
                  {s}
                </span>
              ))}
            </span>
          ) : (
            "none"
          )}
        </Row>
      )}
      <Row label="Model">
        {h.model?.model ? (
          <span className="flex flex-col">
            <span className="font-medium">{modelLine(h.model, choices)}</span>
            {h.model_why && (
              <span className="text-ink-3 text-pretty">{h.model_why}</span>
            )}
          </span>
        ) : choices?.workspace ? (
          `the workspace's (${modelLine(choices.workspace, choices)})`
        ) : (
          "the workspace's"
        )}
      </Row>
      {!forMember && (
        <Row label="Telegram">
          {h.telegram_topic ? "its own topic in the team group" : "no topic"}
        </Row>
      )}
      {h.coding_engine && h.coding_engine !== "hermes" && (
        <Row label="Coding engine">{h.coding_engine} (kept for later)</Row>
      )}
      <div className="mt-2 flex flex-col gap-1.5 border-t border-line pt-2">
        <div className="flex items-center justify-between gap-2">
          <Eyebrow>Kit: what it needs to do the work well</Eyebrow>
          {onKit &&
            (kit ? (
              <button
                type="button"
                className="text-xs text-ink-3 underline decoration-line underline-offset-2 hover:text-ink"
                onClick={() => {
                  onKit(null);
                }}
              >
                Back as proposed
              </button>
            ) : (
              <button
                type="button"
                className="text-xs text-ink-2 underline decoration-line underline-offset-2 hover:text-ink"
                onClick={() => {
                  onKit(structuredClone(proposed));
                }}
              >
                Edit kit
              </button>
            ))}
        </div>
        {kit && onKit && editing && onEdit && choices && (
          <div className="flex flex-col gap-1.5 rounded-xl bg-sunken/60 p-3">
            <Eyebrow>Model</Eyebrow>
            <ModelPicker
              choices={choices}
              value={editing.model}
              onChange={(model) => {
                onEdit({ kit: editing.kit, model });
              }}
            />
            <p className="text-xs text-ink-3">
              Small, repetitive work runs well on a small model with low effort;
              deep work needs a big one with high.
            </p>
          </div>
        )}
        {kit && onKit ? (
          <KitEditor kit={kit} onChange={onKit} />
        ) : h.kit ? (
          <KitView kit={proposed} />
        ) : (
          <p className="text-sm text-danger">
            No kit proposed: fill it with Edit kit before you approve (every
            hire needs its tools, skills, docs and first test).
          </p>
        )}
        {forMember && (
          <p className="text-xs text-ink-3">
            Approve writes it into @{h.member}&apos;s profile the way a
            hire&apos;s kit is written (Undo puts it back). It then goes through
            Readiness: no new work until each item is there, or Start anyway.
          </p>
        )}
      </div>
      {h.source_card && (
        <Row label="From card">
          <Link
            href={`${base}/kanban?card=${encodeURIComponent(h.source_card)}`}
            className="font-mono text-xs underline decoration-line underline-offset-2 hover:decoration-ink"
          >
            {h.source_card}
          </Link>
        </Row>
      )}
    </div>
  );
}
