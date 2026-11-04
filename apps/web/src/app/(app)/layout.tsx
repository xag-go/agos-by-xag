import { cookies } from "next/headers";
import { getAppFacts } from "@/data/queries";
import { AppFactsProvider } from "@/shared/app-facts";
import { MobileTopBar } from "@/features/shell/mobile-drawer";
import { SidebarContent } from "@/features/shell/sidebar";
import { sidebarCookie } from "@/features/shell/sidebar-cookie";
import { SidebarShell } from "@/features/shell/sidebar-shell";
import { requireAccessPage } from "@/server/access-guard";
import { ReloadOnNewBuild } from "@/shared/ui/reload-on-new-build";

export default async function AppLayout({ children }: LayoutProps<"/">) {
  // One wait: the owner check (it sends anyone else away), the sidebar's cookie
  // and the core's limits (read only; never shown unless the check passes).
  const [, jar, facts] = await Promise.all([
    requireAccessPage(),
    cookies(),
    getAppFacts(),
  ]);
  const sidebar = jar.get(sidebarCookie)?.value;
  return (
    <AppFactsProvider facts={facts}>
      <div className="flex min-h-dvh has-[[data-fill]]:h-dvh">
        <ReloadOnNewBuild />
        <SidebarShell initialRail={sidebar === "rail"}>
          <SidebarContent />
        </SidebarShell>

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Small screens: the same sidebar, as an overlay drawer. */}
          <MobileTopBar menu={<SidebarContent />} />

          <main className="app-main min-w-0 flex-1 px-4 py-6 has-[[data-fill]]:flex has-[[data-fill]]:min-h-0 has-[[data-fill]]:flex-col has-[[data-fill]]:overflow-y-auto sm:px-8">
            {children}
          </main>
        </div>
      </div>
    </AppFactsProvider>
  );
}
