import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getSearch, getWorkspace } from "@/data/queries";
import { SEARCH_TYPES, SearchView } from "@/features/search/search-view";

export const metadata: Metadata = { title: "Search" };

export default async function SearchPage({
  params,
  searchParams,
}: PageProps<"/w/[id]/search">) {
  const { id } = await params;
  const query = await searchParams;
  const workspace = await getWorkspace(id);
  if (!workspace) notFound();
  const q = (typeof query.q === "string" ? query.q : "").trim().slice(0, 200);
  const asked = typeof query.types === "string" ? query.types.split(",") : [];
  const types = SEARCH_TYPES.filter((t) => asked.includes(t));
  // One read of the core: every type, each where it lives (Hermes's Kanban and
  // index, the workspace folder, the plan, the team, the skills).
  const page = q
    ? await getSearch(workspace.id, q, types).catch(() => null)
    : null;
  return (
    <SearchView
      baseHref={`/w/${workspace.id}/search`}
      q={q}
      types={types}
      page={page}
    />
  );
}
