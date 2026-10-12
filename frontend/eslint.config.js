import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";
import vueParser from "vue-eslint-parser";
import skipFormatting from "@vue/eslint-config-prettier/skip-formatting";

export default [
  js.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  // Use the underlying parsers directly: the Vue wrapper scans the source tree
  // through fast-glob/micromatch/braces even for this non-type-aware config.
  ...tseslint.configs.recommended.map((config) => ({
    ...config,
    files: ["**/*.{ts,tsx,mts,cts,vue}"],
  })),
  ...pluginVue.configs["flat/base"],
  {
    files: ["**/*.vue"],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: {
          js: "espree",
          jsx: "espree",
          ts: tseslint.parser,
          tsx: tseslint.parser,
        },
        ecmaVersion: 2024,
        ecmaFeatures: { jsx: false },
        extraFileExtensions: [".vue"],
      },
    },
    rules: {
      "vue/block-lang": ["error", { script: { lang: ["ts"], allowNoLang: false } }],
    },
  },
  skipFormatting,
  {
    files: ["src/**/*.{ts,vue}"],
    rules: {
      // Phase B: warn on type-safety issues (fix incrementally, goal: error)
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // PrimeVue uses camelCase props (optionLabel, scrollHeight, etc.)
      "vue/attribute-hyphenation": "off",
      // Cosmetic — low value, keep off
      "vue/multi-word-component-names": "off",
      "vue/attributes-order": "off",
      // Vue prop/template rules — warn for awareness
      "vue/no-required-prop-with-default": "warn",
      "vue/no-template-shadow": "warn",
    },
  },
  { ignores: ["dist/", "node_modules/"] },
];
