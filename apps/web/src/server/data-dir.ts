import os from "node:os";
import path from "node:path";

/** The data folder the core uses: AGOS_DATA_DIR, else ~/agos-data. */
export function dataDir(): string {
  const raw = process.env.AGOS_DATA_DIR?.trim();
  return raw ? raw : path.join(os.homedir(), "agos-data");
}

/** The folder the core writes the internal token into (and, beside it, the
 * saved remote access, ./access.ts). */
export function internalTokenFile(): string {
  const raw = process.env.AGOS_INTERNAL_TOKEN_FILE?.trim();
  return raw ? raw : path.join(dataDir(), "system", "internal.token");
}
