import { cn } from "./cn";

/** The one line under a form that says what happened. */
export function FormStatus({
  error,
  saved,
  savedText = "Saved.",
  className,
}: {
  error: string | null;
  saved?: boolean;
  savedText?: string;
  className?: string;
}) {
  if (error) {
    return (
      <p role="alert" className={cn("text-sm text-danger", className)}>
        {error}
      </p>
    );
  }
  if (saved) {
    return (
      <p role="status" className={cn("text-sm text-success", className)}>
        {savedText}
      </p>
    );
  }
  return null;
}
