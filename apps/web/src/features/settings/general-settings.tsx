"use client";

import { useState, useTransition } from "react";
import { ThemeSwitcher } from "@/features/theme/theme-switcher";
import type { Theme } from "@/features/theme/theme";
import { TAB_SECTIONS } from "@/features/workspaces/tab-sections";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import type {
  FeatureFlag,
  HermesFallback,
  HermesLimitsShown,
  HermesTimeLimits,
  HermesVoice,
} from "@/data/queries";
import type { CatalogProvider } from "@/data/types";
import { FallbackCard } from "./fallback-card";
import { HermesLimitsCard } from "./hermes-limits-card";
import { UpdatesCard } from "./updates-card";
import { LabsCard } from "./labs-card";
import { saveCofounderActionsMode, saveTabsOrder } from "./preferences-actions";
import { TimeLimitsCard } from "./time-limits-card";
import { OwnerNameCard } from "./owner-name-card";
import { TimezoneCard } from "./timezone-card";
import { VoiceCard } from "./voice-card";
import { PanelSection } from "@/shared/ui/panel";

const DEFAULT_ORDER = [
  "dashboard",
  "kanban",
  "sessions",
  "hierarchy",
  "messages",
];

function Card({
  id,
  title,
  description,
  children,
}: {
  id?: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <PanelSection id={id} className="scroll-mt-6 p-5">
      <h3 className="font-medium">{title}</h3>
      <p className="mt-1 text-sm text-ink-2">{description}</p>
      <div className="mt-4">{children}</div>
    </PanelSection>
  );
}

export function GeneralSettings({
  theme,
  tabs,
  cofounderMode,
  timezone,
  ownerName = "",
  hermesLimits,
  hermesTimeLimits,
  hermesFallback,
  hermesVoice,
  modelCatalog,
  flags = [],
}: {
  theme: Theme;
  tabs: string[];
  cofounderMode: "direct" | "ask";
  timezone: string;
  /** His name (one for every workspace; "" = his account's, or none yet). */
  ownerName?: string;
  hermesLimits: HermesLimitsShown;
  hermesTimeLimits: HermesTimeLimits;
  hermesFallback: HermesFallback;
  hermesVoice: HermesVoice;
  modelCatalog: CatalogProvider[];
  /** Settings → General → Labs (the feature flags). */
  flags?: FeatureFlag[];
}) {
  const [mode, setMode] = useState(cofounderMode);
  const [savingMode, startMode] = useTransition();
  const saved = tabs.filter((key) => key in TAB_SECTIONS);
  const [order, setOrder] = useState(saved);
  const [status, setStatus] = useState<"idle" | "saved">("idle");
  const [busy, start] = useTransition();
  const changed = order.join() !== saved.join();

  const move = (index: number, to: number) => {
    if (to < 0 || to >= order.length) return;
    const next = [...order];
    const [item] = next.splice(index, 1);
    if (item !== undefined) next.splice(to, 0, item);
    setOrder(next);
    setStatus("idle");
  };

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Card
        title="Appearance"
        description="Light, dark, or follow this device."
      >
        <div className="w-60">
          <ThemeSwitcher initial={theme} />
        </div>
      </Card>

      <Card
        id="your-name"
        title="Your name"
        description="You are the Founder, beside the Co-Founder in every workspace's Hierarchy. Your cards, your Inbox, your phone notices and the Co-Founder use this name."
      >
        <OwnerNameCard initial={ownerName} />
      </Card>

      <Card
        id="timezone"
        title="Your timezone"
        description="When you tell an agent a time (“at 6”, “tomorrow at 9”), it means this timezone. It is used in every workspace."
      >
        <TimezoneCard initial={timezone} />
      </Card>

      <Card
        title="Updates"
        description="Everything AGOS runs on, in one check. It backs everything up first, updates, and comes back by itself — on the old release if anything fails."
      >
        <UpdatesCard />
      </Card>

      <Card
        title="Workspace menu"
        description="The order of the sections in each workspace's menu (sidebar)."
      >
        <ol
          aria-label="Tab order"
          className="divide-y divide-line rounded-xl border border-line"
        >
          {order.map((key, index) => (
            <li
              key={key}
              className="flex items-center justify-between gap-3 px-4 py-2.5"
            >
              <span className="flex items-center gap-3 text-sm">
                <span className="w-4 text-right text-ink-3 tabular-nums">
                  {index + 1}
                </span>
                {TAB_SECTIONS[key]?.label}
              </span>
              <span className="flex gap-1">
                <Button
                  className="h-8 w-8 !px-0"
                  aria-label={`Move ${TAB_SECTIONS[key]?.label ?? key} up`}
                  disabled={index === 0}
                  onClick={() => move(index, index - 1)}
                >
                  ↑
                </Button>
                <Button
                  className="h-8 w-8 !px-0"
                  aria-label={`Move ${TAB_SECTIONS[key]?.label ?? key} down`}
                  disabled={index === order.length - 1}
                  onClick={() => move(index, index + 1)}
                >
                  ↓
                </Button>
              </span>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex items-center gap-3">
          <Button
            variant="primary"
            disabled={busy || !changed}
            onClick={() =>
              start(async () => {
                await saveTabsOrder(order);
                setStatus("saved");
              })
            }
          >
            Save
          </Button>
          <Button
            disabled={busy || order.join() === DEFAULT_ORDER.join()}
            onClick={() => {
              setOrder(DEFAULT_ORDER);
              setStatus("idle");
            }}
          >
            Reset to default
          </Button>
          {status === "saved" && !changed ? (
            <span role="status" className="text-sm text-ink-2">
              Saved
            </span>
          ) : null}
        </div>
      </Card>

      <Card
        title="What the Co-Founder does from a chat"
        description="Ask the Co-Founder (in the app or on Telegram) to create or change automations, skills, agents or MCP servers, or to turn things on."
      >
        <div
          role="radiogroup"
          aria-label="Co-Founder actions"
          className="flex flex-col gap-2"
        >
          {(
            [
              [
                "direct",
                "Does it at once",
                "Each thing it did shows as a card with Undo. An app that needs your login still waits for you.",
              ],
              [
                "ask",
                "Asks me first",
                "Each thing waits on a card until you press Approve.",
              ],
            ] as const
          ).map(([value, label, help]) => (
            <label
              key={value}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-xl border px-4 py-3",
                mode === value ? "border-ink" : "border-line",
              )}
            >
              <input
                type="radio"
                name="cofounder-mode"
                className="mt-1"
                checked={mode === value}
                disabled={savingMode}
                onChange={() => {
                  setMode(value);
                  startMode(async () => {
                    await saveCofounderActionsMode(value);
                  });
                }}
              />
              <span>
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-sm text-ink-2">{help}</span>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <HermesLimitsCard limits={hermesLimits} />
      <FallbackCard fallback={hermesFallback} catalog={modelCatalog} />
      <TimeLimitsCard limits={hermesTimeLimits} />
      <VoiceCard voice={hermesVoice} />

      <Card
        id="labs"
        title="Labs"
        description="New things that are still being tried. Each one can be turned off again at any time."
      >
        <LabsCard flags={flags} />
      </Card>
    </div>
  );
}
