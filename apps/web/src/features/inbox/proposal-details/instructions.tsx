import { cn } from "@/shared/ui/cn";
import type { InstructionsPayload } from "../proposal-types";
import { Row } from "./row";

export function InstructionsDetails({
  payload: i,
}: {
  payload: InstructionsPayload;
}) {
  const lines = (i.diff ?? "").split("\n");
  return (
    <div className="flex flex-col gap-1">
      <Row label="File">
        <span className="font-mono text-xs">{i.target || "—"}</span>
      </Row>
      {i.summary && <Row label="Why">{i.summary}</Row>}
      {i.diff && (
        <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-sunken px-3 py-2 font-mono text-xs leading-relaxed">
          {lines.map((line, n) => (
            <span
              key={n}
              className={cn(
                "block",
                line.startsWith("+") && !line.startsWith("+++") && "text-live",
                line.startsWith("-") &&
                  !line.startsWith("---") &&
                  "text-danger",
                line.startsWith("@@") && "text-ink-3",
              )}
            >
              {line || " "}
            </span>
          ))}
        </pre>
      )}
      {i.sha256 && (
        <p className="truncate font-mono text-11 text-ink-3">
          sha256 {i.sha256}
        </p>
      )}
    </div>
  );
}
