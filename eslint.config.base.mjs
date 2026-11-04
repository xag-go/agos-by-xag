// Shared ESLint rules for the Node packages (gateway, core, …).
// apps/web uses eslint-config-next and extends only the TS rules from here.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export const typeScriptRules = {
  "@typescript-eslint/consistent-type-imports": "error",
  "@typescript-eslint/no-floating-promises": "error",
  "@typescript-eslint/no-misused-promises": "error",
  "@typescript-eslint/switch-exhaustiveness-check": "error",
  "@typescript-eslint/no-unused-vars": [
    "error",
    { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
  ],
  "no-console": "off",
  eqeqeq: ["error", "always"],
  "no-eval": "error",
  "no-implied-eval": "off",
  "@typescript-eslint/no-implied-eval": "error",
  "no-new-func": "error",
};

/** @param {string} tsconfigRootDir */
export function nodeConfig(tsconfigRootDir) {
  return tseslint.config(
    { ignores: ["dist/**", "node_modules/**"] },
    js.configs.recommended,
    ...tseslint.configs.strictTypeChecked,
    {
      languageOptions: {
        parserOptions: { projectService: true, tsconfigRootDir },
      },
      rules: typeScriptRules,
    },
    {
      // node:test's describe/it return promises the runner itself awaits.
      files: ["**/*.test.ts"],
      rules: {
        "@typescript-eslint/no-floating-promises": [
          "error",
          {
            allowForKnownSafeCalls: [
              {
                from: "package",
                name: ["describe", "it"],
                package: "node:test",
              },
            ],
          },
        ],
      },
    },
    {
      files: ["**/*.mjs", "**/*.js"],
      ...tseslint.configs.disableTypeChecked,
    },
  );
}
