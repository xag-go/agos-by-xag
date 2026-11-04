// The function-complexity ratchet's own ESLint run (scripts/ci/complexity.py --part web):
// syntax only (no type information, so it is fast), and only the two measures it records.
// The limits are the script's WEB_LIMITS; the baseline is scripts/ci/complexity-baseline.json.
import tseslint from "typescript-eslint";

const config = [
  {
    files: ["src/**/*.ts", "src/**/*.tsx"],
    ignores: ["src/data/core-api.d.ts"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    rules: {
      complexity: ["warn", 10],
      "max-lines-per-function": [
        "warn",
        { max: 80, skipBlankLines: true, skipComments: true },
      ],
    },
  },
];

export default config;
