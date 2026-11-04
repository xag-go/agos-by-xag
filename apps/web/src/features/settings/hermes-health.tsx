"use client";

import { useEffect, useState, useTransition } from "react";
import type { HermesHealth } from "@/data/queries";
import { TimeAgo } from "@/shared/time-ago";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/ui/cn";
import { FormStatus } from "@/shared/ui/form-status";
import { runHermesHealth } from "./hermes-health-actions";
import { PanelSection } from "@/shared/ui/panel";

type Report = HermesHealth["roots"][number]["status"];

function Counts({ report }: { report: Report }) {
  // Its first run since the core started is on its way: not an error.
  if (report.pending) return <span className="text-ink-2">Checking…</span>;
  if (report.error) return <span className="text-danger">not read</span>;
  // Hermes's own yes/no (doctor's exit code); the counts are its ✗/⚠ marks.
  const bad = report.hasProblems ?? report.problems > 0;
  return (
    <span
      className={cn(
        bad ? "text-danger" : report.warnings > 0 ? "text-ink" : "text-ink-2",
      )}
    >
      {report.hasProblems === true
        ? "Has problems · "
        : report.hasProblems === false
          ? "No problems · "
          : ""}
      {report.problems} problem{report.problems === 1 ? "" : "s"},{" "}
      {report.warnings} warning{report.warnings === 1 ? "" : "s"}
    </span>
  );
}

function ReportBlock({ title, report }: { title: string; report: Report }) {
  return (
    <details className="rounded-xl border border-line">
      <summary className="flex cursor-pointer items-center justify-between gap-3 px-4 py-2 text-sm">
        <code>{title}</code>
        <Counts report={report} />
      </summary>
      {report.pending ? (
        <p className="px-4 pb-3 text-sm text-ink-2">Hermes is checking…</p>
      ) : report.error ? (
        <p className="px-4 pb-3 text-sm text-danger">{report.error}</p>
      ) : (
        <pre className="max-h-[32rem] overflow-auto px-4 pb-3 text-xs leading-relaxed whitespace-pre-wrap text-ink-2">
          {report.text}
        </pre>
      )}
    </details>
  );
}

/** Settings → Health: Hermes's own reports, never AGOS's own checks. The last
 * reports show at once; "Run again" asks Hermes behind the page and the page
 * asks the core again every few seconds until the new ones are in. */
export function HermesHealthView() {
  const [data, setData] = useState<HermesHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, start] = useTransition();
  const checking = data?.roots.some((root) => root.checking) ?? false;

  const run = (fresh: boolean) => {
    start(async () => {
      const got = await runHermesHealth(fresh);
      if (got.ok) {
        setData(got.data);
        setError(null);
      } else setError(got.error);
    });
  };

  useEffect(() => {
    run(false);
  }, []);

  useEffect(() => {
    if (!checking) return;
    const timer = setTimeout(() => {
      void runHermesHealth(false).then((got) => {
        if (got.ok) setData(got.data);
      });
    }, 3000);
    return () => {
      clearTimeout(timer);
    };
  }, [checking, data]);

  return (
    <PanelSection
      aria-labelledby="hermes-health"
      className="flex max-w-4xl flex-col gap-4 p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 id="hermes-health" className="font-medium">
            Hermes&apos;s checks
          </h3>
          <p className="mt-1 text-sm text-ink-2">
            Runs Hermes&apos;s own <code>hermes status --full</code> and{" "}
            <code>hermes doctor</code> (without --fix) in each workspace&apos;s
            Hermes. Nothing is changed. The Co-Founder can run them for you from
            a chat too.
          </p>
        </div>
        <Button
          variant="primary"
          disabled={busy || checking}
          onClick={() => {
            run(true);
          }}
        >
          {busy || checking
            ? "Checking…"
            : data
              ? "Run again"
              : "Run Hermes's checks"}
        </Button>
      </div>
      <FormStatus error={error} />
      {data && data.roots.length === 0 ? (
        <p className="text-sm text-ink-2">
          No workspace&apos;s Hermes is set up yet.
        </p>
      ) : null}
      {data?.roots.map((root) => (
        <div key={root.workspaceId} className="flex flex-col gap-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="font-medium">{root.name}</h4>
            <code className="text-xs break-all text-ink-3">{root.home}</code>
          </div>
          <p className="text-xs text-ink-3">
            {root.checking ? (
              "Checking…"
            ) : root.checkedAt ? (
              <>
                Last checked: <TimeAgo iso={root.checkedAt} />
              </>
            ) : null}
          </p>
          <ReportBlock title="hermes doctor" report={root.doctor} />
          <ReportBlock title="hermes status --full" report={root.status} />
        </div>
      ))}
    </PanelSection>
  );
}
