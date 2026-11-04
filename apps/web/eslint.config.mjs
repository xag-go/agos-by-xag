import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import tseslint from "typescript-eslint";
import { typeScriptRules } from "../../eslint.config.base.mjs";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["**/*.ts", "**/*.tsx"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: typeScriptRules,
  },
  {
    // three.js scenes mutate cameras, meshes and controllers every frame by design
    files: ["src/features/office3d/**/*.tsx"],
    rules: { "react-hooks/immutability": "off" },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
