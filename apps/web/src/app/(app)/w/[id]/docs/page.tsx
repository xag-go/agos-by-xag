import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getDoc, getDocs, getWorkspace } from "@/data/queries";
import { DocsView } from "@/features/docs/docs-view";

export const metadata: Metadata = { title: "Documentation" };

export default async function DocsPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/docs">) {
  const { id } = await params;
  const query = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const wanted = typeof query.f === "string" ? query.f : "README.md";
  // The file asked for is read with the index (it nearly always exists); only
  // when the index has no such file is its first one read after it.
  const [index, asked] = await Promise.all([
    getDocs(workspace.id),
    getDoc(workspace.id, wanted).catch(() => null),
  ]);
  const path = index.files.some((f) => f.path === wanted)
    ? wanted
    : index.files[0]?.path;
  const open =
    path === wanted
      ? asked
      : path
        ? await getDoc(workspace.id, path).catch(() => null)
        : null;
  return <DocsView workspaceId={workspace.id} index={index} open={open} />;
}
