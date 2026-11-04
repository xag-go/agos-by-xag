// Node test loader for the web's .ts/.tsx modules (component and hook tests under
// `node --test --import ./scripts/tsx-loader.mjs`): TypeScript's own transpiler turns TSX into
// plain JS (React's automatic JSX runtime), and `@/x` imports resolve to `src/x` like
// tsconfig's paths. No bundler, no new dependency: `typescript` is the repo's own.
import { register } from "node:module";

register("./tsx-hooks.mjs", import.meta.url);
