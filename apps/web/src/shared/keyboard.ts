/** True when a key press belongs to a text field (or, with `dialogs`, to
 * anything inside an open dialog), so a page's one-key shortcuts stay quiet. */
export function typing(
  target: EventTarget | null,
  { dialogs = false }: { dialogs?: boolean } = {},
): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    (dialogs && target.closest("dialog") !== null)
  );
}
