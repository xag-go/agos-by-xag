// Stand-in for next/link in web unit tests (scripts/tsx-hooks.mjs): a plain anchor.
import { createElement } from "react";

export default function Link({ href, ...rest }) {
  delete rest.prefetch;
  return createElement("a", { href: String(href), ...rest });
}
