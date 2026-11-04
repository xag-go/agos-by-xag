import { cookies } from "next/headers";
import { getTabsOrder, getWorkspaces } from "@/data/queries";
import { parseTheme, themeCookie } from "@/features/theme/theme";
import { ThemeToggle } from "@/features/theme/theme-switcher";
import { RailPulseProvider } from "./rail-pulse";
import { WorkspaceRail } from "./workspace-rail";
import { WorkspaceSections } from "./workspace-sections";
import { WorkspaceHeader } from "./workspace-current";
import { SidebarFoot } from "./sidebar-foot";

/**
 * The sidebar's content: the workspace rail (every workspace, one tile each)
 * beside the panel of the workspace you're in (its name and its sections), and
 * under both one foot bar: general Settings and the theme. In the slim state
 * (`group-data-[rail]/side`) the panel folds away; the rail and the foot stay.
 */
export async function SidebarContent() {
  const [workspaces, tabs, jar] = await Promise.all([
    getWorkspaces(),
    getTabsOrder(),
    cookies(),
  ]);
  const list = workspaces.map((w) => ({
    id: w.id,
    name: w.name,
    icon: w.icon ?? null,
  }));
  const theme = parseTheme(jar.get(themeCookie)?.value);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <RailPulseProvider enabled={list.length > 0}>
        <div className="flex min-h-0 flex-1">
          <WorkspaceRail workspaces={list} order={tabs.order} />
          <div className="agos-panel h-full w-[228px] overflow-hidden transition-[width,opacity] duration-300 ease-glide group-data-[rail]/side:pointer-events-none group-data-[rail]/side:w-0 group-data-[rail]/side:opacity-0">
            <div className="flex h-full w-[228px] flex-col gap-4 overflow-y-auto p-3 pl-2.5">
              <WorkspaceHeader workspaces={list} />
              <WorkspaceSections workspaces={list} order={tabs.order} />
            </div>
          </div>
        </div>
      </RailPulseProvider>

      <SidebarFoot
        theme={
          <ThemeToggle
            initial={theme}
            className="group/item relative grid size-9 place-items-center rounded-lg text-ink-2 transition-colors hover:bg-ink/4.5 hover:text-ink"
          />
        }
      />
    </div>
  );
}
