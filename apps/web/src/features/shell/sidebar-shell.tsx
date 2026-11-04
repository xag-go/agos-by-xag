"use client";

import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { cn } from "@/shared/ui/cn";
import { SidebarIcon } from "@/shared/ui/icons";
import { sidebarCookie } from "./sidebar-cookie";

/**
 * The desktop sidebar: the workspace rail plus the workspace's panel, or the
 * rail alone. The choice is kept in a cookie so the server renders the right
 * width (no jump on load). Toggle with the Hide button at the panel's top
 * right, the Show button in the rail, or ⌘/Ctrl + B. Children style
 * themselves with `group-data-[rail]/side:` (the panel fades).
 * On the app's own pages (general Settings, a new workspace) there is no
 * workspace panel to show, so only the rail stays.
 */
type SidebarState = { rail: boolean; inWorkspace: boolean; toggle: () => void };

/** Null outside the desktop sidebar (the small-screen menu renders the same
 * content without a shell), where the toggle buttons have nothing to do. */
const SidebarContext = createContext<SidebarState | null>(null);

export function SidebarShell({
  initialRail,
  children,
}: {
  initialRail: boolean;
  children: React.ReactNode;
}) {
  const [chosenRail, setRail] = useState(initialRail);
  const inWorkspace = /^\/w\//.test(usePathname());
  const rail = chosenRail || !inWorkspace;

  const toggle = useCallback(() => {
    setRail((was) => {
      const next = !was;
      document.cookie = `${sidebarCookie}=${next ? "rail" : "full"}; path=/; max-age=31536000; samesite=lax`;
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        !event.altKey &&
        event.key.toLowerCase() === "b"
      ) {
        const target = event.target as HTMLElement | null;
        // Leave ⌘B to text editors (bold) when typing.
        if (target?.closest("input, textarea, [contenteditable=true]")) return;
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [toggle]);

  return (
    <SidebarContext.Provider value={{ rail, inWorkspace, toggle }}>
      <aside
        data-rail={rail || undefined}
        className={cn(
          "agos-sidebar group/side sticky z-30 hidden shrink-0 transition-[width] duration-300 ease-glide lg:block",
          rail ? "w-16" : "w-[292px]",
        )}
      >
        {children}
      </aside>
    </SidebarContext.Provider>
  );
}

/** Top right of the workspace panel: folds it away, leaving the rail. */
export function SidebarCollapseButton() {
  const side = useContext(SidebarContext);
  if (!side) return null;
  return (
    <button
      type="button"
      onClick={side.toggle}
      aria-label="Hide the workspace menu"
      title="Hide the workspace menu (⌘B)"
      className="grid size-8 shrink-0 place-items-center rounded-7 border border-line bg-sunken text-ink-2 transition-colors hover:bg-ink/6 hover:text-ink"
    >
      <SidebarIcon open />
    </button>
  );
}

/** In the rail, under the mark, only while the panel is folded: brings it back. */
export function SidebarOpenButton() {
  const side = useContext(SidebarContext);
  if (!side || !side.rail || !side.inWorkspace) return null;
  return (
    <button
      type="button"
      onClick={side.toggle}
      aria-label="Show the workspace menu"
      title="Show the workspace menu (⌘B)"
      className="grid h-[30px] w-[34px] shrink-0 place-items-center rounded-lg border border-line bg-transparent text-ink-2 transition-colors hover:bg-ink/6 hover:border-line-strong hover:text-ink"
    >
      <SidebarIcon open={false} />
    </button>
  );
}
