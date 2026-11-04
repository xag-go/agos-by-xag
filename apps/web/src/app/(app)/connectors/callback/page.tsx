import type { Metadata } from "next";
import Link from "next/link";
import type { AppFlow } from "@/data/types";
import { core, CoreError } from "@/server/core";
import { buttonClass } from "@/shared/ui/button";

export const metadata: Metadata = { title: "Connecting an app" };
export const dynamic = "force-dynamic";

function one(value: string | string[] | undefined): string | undefined {
  const v = Array.isArray(value) ? value[0] : value;
  return v && v.length <= 4000 ? v : undefined;
}

/** The app's login page sends the browser back here; the core finishes it. */
export default async function ConnectorCallback({
  searchParams,
}: PageProps<"/connectors/callback">) {
  const params = await searchParams;
  const state = one(params.state);
  let result: AppFlow | null = null;
  let problem: string | null = null;
  if (!state) {
    problem = "This link isn't a login answer.";
  } else {
    try {
      result = await core<AppFlow>("POST", "/apps/callback", {
        state,
        code: one(params.code) ?? null,
        error: one(params.error) ?? null,
        iss: one(params.iss) ?? null,
      });
    } catch (error) {
      problem =
        error instanceof CoreError
          ? error.detail
          : "The login couldn't finish.";
    }
  }
  const ok = result?.status === "connected";
  return (
    <div className="mx-auto flex max-w-lg flex-col gap-4 py-10">
      <h1 className="font-display text-xl font-semibold">
        {ok ? "App connected" : "The app wasn't connected"}
      </h1>
      <p className="text-sm text-ink-2">
        {ok
          ? "It's on in this workspace now, with the account you just used. If the Co-Founder asked for it in a chat, it carries on there."
          : (problem ?? result?.error ?? "The login didn't finish in time.")}
      </p>
      <Link
        href={
          result?.workspaceId
            ? `/w/${encodeURIComponent(result.workspaceId)}/settings/capabilities`
            : "/"
        }
        className={buttonClass("primary", "self-start")}
      >
        {result?.workspaceId ? "Back to the workspace's apps" : "Back"}
      </Link>
    </div>
  );
}
