import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getWorkspaces } from "@/data/queries";
import { AgosByline, AgosMark } from "@/features/shell/agos-logo";
import { lastWorkspaceCookie } from "@/features/shell/workspace-current";
import { ButtonLink } from "@/shared/ui/button";
import { PlusIcon } from "@/shared/ui/icons";

export const metadata: Metadata = { title: "AGOS" };

/** Home: the last workspace opened (else the first), or how to start. */
export default async function HomePage() {
  const workspaces = await getWorkspaces();
  const lastId = (await cookies()).get(lastWorkspaceCookie)?.value;
  const open = workspaces.find((w) => w.id === lastId) ?? workspaces[0];
  if (!open) return <Welcome />;
  redirect(`/w/${open.id}`);
}

/** A fresh install: no workspace yet, one way forward. */
function Welcome() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 text-center">
      <div className="flex flex-col items-center gap-1.5">
        <AgosMark id="agos-mark-home" className="size-14" />
        <AgosByline className="text-10" />
      </div>
      <div className="flex max-w-md flex-col gap-2">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          No workspace yet
        </h1>
        <p className="text-ink-2">
          A workspace is one project — your store, your investments, your
          content — with its own folder, Kanban, chats and team.
        </p>
      </div>
      <ButtonLink href="/new" variant="primary">
        <PlusIcon />
        Create your first workspace
      </ButtonLink>
      <p className="text-sm text-ink-3">
        You can connect Claude, OpenAI or Gemini in{" "}
        <Link href="/settings/models" className="underline underline-offset-2">
          Settings → Models
        </Link>
        .
      </p>
    </div>
  );
}
