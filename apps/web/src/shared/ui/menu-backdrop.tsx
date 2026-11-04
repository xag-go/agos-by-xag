/** The invisible full-screen button behind an open menu: a click outside the
 * menu closes it. */
export function MenuBackdrop({
  onClose,
  label = "Close menu",
}: {
  onClose: () => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className="fixed inset-0 z-20 cursor-default"
      onClick={onClose}
    />
  );
}
