import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getKanban,
  getSkillTests,
  getSkillVersions,
  getWorkspace,
  getWorkspaceSkills,
  parseId,
} from "@/data/queries";
import { SkillStudio } from "@/features/library/skill-studio";

export const metadata: Metadata = { title: "Skill" };

/** Skill Studio: one workspace skill's versions and test runs (one read per tab). */
export default async function SkillStudioPage({
  params,
}: PageProps<"/w/[id]/settings/capabilities/skills/[itemId]">) {
  const { id, itemId } = await params;
  const item_id = parseId(itemId);
  if (item_id === null) notFound();
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const skills = await getWorkspaceSkills(workspace.id);
  const item = skills.find((s) => s.id === item_id);
  if (!item) notFound();
  const [versions, tests, board] = await Promise.all([
    getSkillVersions(workspace.id, item.id),
    getSkillTests(workspace.id, item.id),
    getKanban(workspace.id),
  ]);
  return (
    <>
      <div>
        <Link
          href={`/w/${encodeURIComponent(workspace.id)}/settings/capabilities`}
          className="text-sm text-ink-2 hover:text-ink"
        >
          ← Capabilities
        </Link>
        <h2 className="mt-1 font-display text-lg font-semibold">
          {item.title}{" "}
          <span className="font-mono text-sm text-ink-3">{item.name}</span>
        </h2>
        <p className="max-w-2xl text-sm text-ink-2">
          Its versions from Hermes&apos;s skill ledger, and its test runs on the
          board.
        </p>
      </div>
      <SkillStudio
        workspaceId={workspace.id}
        item={item}
        versions={versions}
        tests={tests}
        members={board?.members ?? [{ name: "cofounder", title: "Co-Founder" }]}
      />
    </>
  );
}
