import type { SkillPayload } from "../proposal-types";
import { Row } from "./row";

export function SkillDetails({ payload: s }: { payload: SkillPayload }) {
  return (
    <div className="flex flex-col gap-1">
      <Row label="Asked by">@{s.member || "cofounder"}</Row>
      <Row label="For">{s.why || "—"}</Row>
      <Row label="Source">
        <code className="text-xs break-all">{s.source}</code>
      </Row>
      <Row label="Why you">{s.asked || "—"}</Row>
      <Row label="Tested">
        {s.tested
          ? "Passed the agent's tests in Skill Studio"
          : "After your yes: Hermes installs it, then the agent's tests run"}
      </Row>
      {s.scan && (
        <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-sunken px-2 py-1 text-xs whitespace-pre-wrap text-ink-2">
          {s.scan}
        </pre>
      )}
    </div>
  );
}
