/** GETs a small status from one of the app's own /api routes, for the pages'
 * polls. Not a server action on purpose: Next runs server actions one at a
 * time, so a poll in flight made every click on the page wait behind it.
 * null = no answer (the route refused, or the network failed). */
export async function getStatus<T>(url: string): Promise<T | null> {
  try {
    const response = await fetch(url, { cache: "no-store" });
    return response.ok ? ((await response.json()) as T) : null;
  } catch {
    return null;
  }
}
