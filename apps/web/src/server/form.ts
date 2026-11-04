import "server-only";
import { modelSelectionSchema, type ModelSelection } from "@agos/core";

/** What every form action returns to its form. */
export type FormState = { error: string | null; saved?: boolean };

/** A trimmed text field; missing or non-text counts as "". */
export function field(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value.trim() : "";
}

/** A checkbox or switch: present with any value = on. */
export function checked(form: FormData, name: string): boolean {
  return form.get(name) !== null;
}

/** The model picker's hidden JSON field, validated. */
export function modelField(
  form: FormData,
  name = "model",
): ModelSelection | null {
  try {
    const parsed = modelSelectionSchema.safeParse(
      JSON.parse(field(form, name)),
    );
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/** Lines of a textarea, trimmed, empty ones dropped. */
export function lines(
  form: FormData,
  name: string,
  maxItems: number,
): string[] {
  return field(form, name)
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .slice(0, maxItems);
}

/** Runs a core call for a form; a refusal from the core becomes the form's error. */
export async function attempt(
  fn: () => Promise<unknown>,
  saved = true,
): Promise<FormState> {
  const { CoreError } = await import("./core");
  try {
    await fn();
    return { error: null, saved };
  } catch (error) {
    if (error instanceof CoreError && error.status < 500)
      return { error: error.detail };
    throw error;
  }
}
