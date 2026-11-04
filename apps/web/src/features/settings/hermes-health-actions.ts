"use server";

import type { HermesHealth } from "@/data/queries";
import { type Answer, carry } from "@/server/action";
import { core } from "@/server/core";

/** Hermes's own `hermes status --full` and `hermes doctor` of every workspace's
 * root, as last taken (at once). `fresh` asks Hermes again behind the page (a few
 * seconds each): the answer then says `checking` until the new reports are in. */
export async function runHermesHealth(
  fresh = false,
): Promise<Answer<HermesHealth>> {
  return carry(() =>
    core<HermesHealth>(
      "GET",
      `/preferences/hermes-health${fresh ? "?fresh=true" : ""}`,
    ),
  );
}
