// The accessibility ratchet's own ESLint run (scripts/ci/a11y_lint.py): eslint-plugin-jsx-a11y's
// recommended rules plus control-has-associated-label (a button or link with no name), syntax
// only (no type information, so it is fast). Every rule warns; the gate is the script's
// baseline (scripts/ci/a11y-baseline.json), which only shrinks.
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

const recommended = jsxA11y.flatConfigs.recommended.rules;
const warn = (setting) =>
  Array.isArray(setting) ? ["warn", ...setting.slice(1)] : "warn";
const on = (setting) =>
  (Array.isArray(setting) ? setting[0] : setting) !== "off";

const rules = Object.fromEntries(
  Object.entries(recommended)
    .filter(([, setting]) => on(setting))
    .map(([name, setting]) => [name, warn(setting)]),
);
rules["jsx-a11y/control-has-associated-label"] = warn(
  recommended["jsx-a11y/control-has-associated-label"],
);
// The settings cards' labels hold their text two spans deep (<label><input/><span><span>
// title</span>…): the browser names the control from it, the rule's default depth (2)
// doesn't see it.
rules["jsx-a11y/label-has-associated-control"] = ["warn", { depth: 3 }];

const config = [
  {
    files: ["src/**/*.tsx"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    plugins: { "jsx-a11y": jsxA11y },
    // <Panel as="section"> is checked as the <section> it renders.
    settings: {
      "jsx-a11y": {
        polymorphicPropName: "as",
        components: { Panel: "div", PanelSection: "section" },
      },
    },
    rules,
  },
];

export default config;
