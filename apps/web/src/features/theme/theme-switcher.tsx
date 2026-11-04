"use client";

import { useState } from "react";
import { cn } from "@/shared/ui/cn";
import { AutoIcon, MoonIcon, SunIcon } from "@/shared/ui/icons";
import { RailTip } from "@/features/shell/nav-link";
import { themeCookie, themes, type Theme } from "./theme";

const labels: Record<Theme, string> = {
  system: "Auto",
  light: "Light",
  dark: "Dark",
};

const icons: Record<Theme, () => React.JSX.Element> = {
  system: AutoIcon,
  light: SunIcon,
  dark: MoonIcon,
};

/** Applies the theme to the page now and remembers it for the next visit. */
function applyTheme(next: Theme) {
  const root = document.documentElement;
  if (next === "system") delete root.dataset.theme;
  else root.dataset.theme = next;
  document.cookie = `${themeCookie}=${next}; path=/; max-age=31536000; samesite=lax`;
}

/**
 * Switches the theme at once (data-theme on <html>) and remembers it in a
 * cookie, so the server renders the right colors on the next visit.
 */
export function ThemeSwitcher({ initial }: { initial: Theme }) {
  const [theme, setTheme] = useState(initial);

  function pick(next: Theme) {
    setTheme(next);
    applyTheme(next);
  }

  const index = themes.indexOf(theme);
  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="relative grid grid-cols-3 rounded-xl bg-sunken p-1"
    >
      {/* The pill slides to the picked theme. */}
      <span
        aria-hidden
        className="absolute inset-y-1 left-1 w-[calc((100%-0.5rem)/3)] rounded-lg bg-panel shadow-thumb transition-transform duration-300 ease-glide"
        style={{ transform: `translateX(${index * 100}%)` }}
      />
      {themes.map((t) => {
        const Icon = icons[t];
        return (
          <button
            key={t}
            type="button"
            role="radio"
            aria-checked={theme === t}
            aria-label={labels[t]}
            title={labels[t]}
            onClick={() => {
              pick(t);
            }}
            className={cn(
              "relative z-10 flex h-7 items-center justify-center gap-1.5 rounded-lg text-xs transition-colors",
              theme === t
                ? "font-medium text-ink"
                : "text-ink-3 hover:text-ink",
            )}
          >
            <Icon />
            <span>{labels[t]}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * One button that steps through Auto → Light → Dark (the sidebar's foot). The
 * icon is the theme in use; the tooltip says what the next click gives.
 */
export function ThemeToggle({
  initial,
  className,
}: {
  initial: Theme;
  className?: string;
}) {
  const [theme, setTheme] = useState(initial);
  const next = themes[(themes.indexOf(theme) + 1) % themes.length] ?? "system";
  const Icon = icons[theme];
  const text = `Theme: ${labels[theme]} (click for ${labels[next]})`;
  return (
    <button
      type="button"
      aria-label={text}
      onClick={() => {
        setTheme(next);
        applyTheme(next);
      }}
      className={className}
    >
      <Icon />
      <RailTip always>{text}</RailTip>
    </button>
  );
}
