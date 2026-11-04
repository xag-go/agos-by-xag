export function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-2 text-sm">
      <span className="w-24 shrink-0 text-ink-3">{label}</span>
      <span className="min-w-0 flex-1 text-ink">{children}</span>
    </div>
  );
}
