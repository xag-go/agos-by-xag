import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getScreen, getWorkspace } from "@/data/queries";
import { LiveScreen } from "@/features/screen/live-screen";

export const metadata: Metadata = { title: "Screen" };

export default async function ScreenPage({
  params,
}: PageProps<"/w/[id]/screen">) {
  const { id } = await params;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const screen = await getScreen(workspace.id);
  return (
    <section className="flex flex-col gap-4">
      <div>
        <h2 className="font-display text-xl font-semibold">Screen</h2>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          This workspace&apos;s own computer: the browser and desktop its agents
          use. It runs inside the workspace&apos;s sandbox, never on your
          machine, and only reaches the public internet.
        </p>
      </div>
      {screen.enabled ? (
        <LiveScreen
          workspaceId={workspace.id}
          idleStopMinutes={screen.idleStopMinutes ?? null}
        />
      ) : (
        <div className="rounded-xl border border-line p-6 text-sm text-ink-2">
          No screen yet. Turn on <strong>Browser</strong> or{" "}
          <strong>Computer use</strong> in{" "}
          <Link
            href={`/w/${workspace.id}/settings/capabilities`}
            className="text-accent underline-offset-2 hover:underline"
          >
            Capabilities
          </Link>{" "}
          to give this workspace its own screen.
        </div>
      )}
    </section>
  );
}
