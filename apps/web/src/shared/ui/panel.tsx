import {
  createElement,
  type ComponentPropsWithoutRef,
  type ElementType,
} from "react";
import { cn } from "./cn";

/**
 * The card surface the screens share: rounded corners, a hairline border, the panel
 * background. Owns only that surface; padding, layout and spacing stay with the caller
 * (`<Panel as="section" className="flex flex-col gap-4 p-5">`).
 */
export const PANEL = "rounded-2xl border border-line bg-panel";

type PanelProps<T extends ElementType> = { as?: T } & Omit<
  ComponentPropsWithoutRef<T>,
  "as"
>;

/** A card: the element `as` names (a `div` by default) with the shared surface classes. */
export function Panel<T extends ElementType = "div">({
  as,
  className,
  ...rest
}: PanelProps<T>) {
  return createElement(as ?? "div", {
    ...rest,
    className: cn(PANEL, className),
  });
}

/** A card that is a page section (`<section>`), the most common card. */
export function PanelSection(props: Omit<PanelProps<"section">, "as">) {
  return <Panel as="section" {...props} />;
}
