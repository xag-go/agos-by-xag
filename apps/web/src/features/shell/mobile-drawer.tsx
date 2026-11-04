"use client";

import { usePathname } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { MenuIcon } from "@/shared/ui/icons";

/**
 * Small screens only (the desktop sidebar is hidden there): a top bar with a
 * real menu button, and the same sidebar content as an overlay drawer. The
 * backdrop, Escape and navigating anywhere close it; the page behind it does
 * not scroll while it is open. On the app's own pages (general Settings, a
 * new workspace) there is no workspace panel, so the drawer is the rail alone
 * — same rule as the desktop sidebar.
 */
export function MobileTopBar({ menu }: { menu: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const inWorkspace = /^\/w\//.test(pathname);
  const opener = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);

  // Navigating closes the drawer (the adjust-during-render pattern; an
  // effect calling setState is rejected by the React compiler lint).
  const [lastPath, setLastPath] = useState(pathname);
  if (lastPath !== pathname) {
    setLastPath(pathname);
    setOpen(false);
  }

  useDrawerKeys(open, setOpen, opener, drawer);

  return (
    <div className="border-b border-line lg:hidden">
      <div className="flex h-13 items-center px-1.5">
        <button
          ref={opener}
          type="button"
          aria-label="Open the menu"
          aria-expanded={open}
          aria-controls="agos-mobile-drawer"
          onClick={() => {
            setOpen(true);
          }}
          className="flex h-11 min-w-11 items-center gap-2.5 rounded-lg px-2.5 font-display font-bold transition-colors active:bg-ink/6"
        >
          <MenuIcon />
          AGOS
        </button>
      </div>

      {open && (
        <div
          id="agos-mobile-drawer"
          role="dialog"
          aria-modal="true"
          aria-label="Menu"
          className="fixed inset-0 z-50"
        >
          <button
            type="button"
            aria-label="Close the menu"
            onClick={() => {
              setOpen(false);
              opener.current?.focus();
            }}
            className="agos-drawer-backdrop absolute inset-0 w-full bg-black/50"
          />
          <div
            ref={drawer}
            tabIndex={-1}
            data-rail={inWorkspace ? undefined : true}
            onClick={(event) => {
              // A tap on any link in the drawer closes it, even when the
              // link points at the page already shown.
              if ((event.target as HTMLElement).closest("a")) setOpen(false);
            }}
            className="agos-sidebar agos-drawer group/side relative outline-none"
          >
            {menu}
          </div>
        </div>
      )}
    </div>
  );
}

/** While the drawer is open: the page behind it does not scroll, focus moves
 * into it, and Escape closes it, back to the button that opened it. */
function useDrawerKeys(
  open: boolean,
  setOpen: (open: boolean) => void,
  opener: RefObject<HTMLButtonElement | null>,
  drawer: RefObject<HTMLDivElement | null>,
) {
  // The page behind the drawer must not scroll.
  useEffect(() => {
    if (!open) return;
    const was = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer.current?.focus();
    return () => {
      document.body.style.overflow = was;
    };
  }, [open, drawer]);

  // Escape closes, back to the button that opened it.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        opener.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [open, opener, setOpen]);
}
