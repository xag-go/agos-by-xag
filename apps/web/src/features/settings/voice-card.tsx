"use client";

import { useState, useTransition } from "react";
import { AllHermesSettingsLink } from "./hermes-settings";
import type { HermesVoice } from "@/data/queries";
import { Button } from "@/shared/ui/button";
import { saveHermesVoice } from "./preferences-actions";
import { PanelSection } from "@/shared/ui/panel";

/** The "Off" choice (Hermes's stt.enabled: false), where a new install starts. */
const OFF = "off";

/** Who hears the owner's voice notes: Hermes's own speech-to-text choice
 * (stt.provider and that provider's model), one value for every workspace in
 * Hermes's managed settings, which they all read (AGOS keeps no copy). */
export function VoiceCard({ voice }: { voice: HermesVoice }) {
  const [provider, setProvider] = useState(voice.provider);
  const [model, setModel] = useState(voice.model);
  const [note, setNote] = useState<string | null>(null);
  const [saving, startSave] = useTransition();
  const option = voice.options.find((o) => o.name === provider);
  const known = voice.options.some((o) => o.name === voice.provider);
  const changed = provider !== voice.provider || model !== voice.model;
  const off = provider === OFF;
  const listId = "voice-note-models";

  return (
    <PanelSection id="voice-notes" className="scroll-mt-6 p-5">
      <h3 className="font-medium">Voice notes</h3>
      <p className="mt-1 text-sm text-ink-2">
        Who turns your voice notes into text before the agent reads them. It is
        Hermes&apos;s own speech-to-text setting (stt.provider and its model):
        one choice for every workspace and every member ({voice.profiles} Hermes
        profiles), saved once into Hermes&apos;s managed settings, which they
        all read. Off until you pick one. Gemini comes from AGOS&apos;s plugin
        for Hermes; the others are Hermes&apos;s own.
      </p>

      <div className="mt-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            Provider
            <select
              aria-label="Voice-note provider"
              value={provider}
              disabled={saving}
              onChange={(e) => {
                const next = e.target.value;
                setProvider(next);
                const first = voice.options.find((o) => o.name === next)
                  ?.models[0];
                setModel(next === voice.provider ? voice.model : (first ?? ""));
                setNote(null);
              }}
              className="h-9 w-64 rounded-lg border border-line bg-panel px-3 text-sm"
            >
              {!known && (
                <option value={voice.provider}>
                  {voice.provider || "Not set (Hermes picks one)"}
                </option>
              )}
              {voice.options.map((o) => (
                <option key={o.name} value={o.name}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {!off && (
            <label className="flex items-center gap-2 text-sm">
              Model
              <input
                aria-label="Voice-note model"
                list={listId}
                value={model}
                disabled={saving}
                placeholder="Hermes's default"
                onChange={(e) => {
                  setModel(e.target.value);
                  setNote(null);
                }}
                className="h-9 w-64 rounded-lg border border-line bg-panel px-3 text-sm"
              />
              <datalist id={listId}>
                {(option?.models ?? []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
            </label>
          )}
        </div>
        {option && (
          <span className="block text-sm text-ink-2">
            {option.hint}{" "}
            <span className="font-mono text-xs text-ink-3">
              {off
                ? "stt.enabled: false"
                : `stt.provider: ${option.name}${model ? ` · ${option.modelKey}: ${model}` : ""}`}
            </span>
          </span>
        )}
        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            disabled={saving || !changed || !option}
            onClick={() => {
              setNote(null);
              startSave(async () => {
                const r = await saveHermesVoice(provider, model);
                setNote(r.error ?? "Saved in Hermes.");
              });
            }}
          >
            Save
          </Button>
          {changed && (
            <Button
              disabled={saving}
              onClick={() => {
                setProvider(voice.provider);
                setModel(voice.model);
                setNote(null);
              }}
            >
              Undo changes
            </Button>
          )}
          {note && (
            <span role="status" className="text-sm text-ink-2">
              {note}
            </span>
          )}
        </div>
      </div>
      <AllHermesSettingsLink search="stt" />
    </PanelSection>
  );
}
