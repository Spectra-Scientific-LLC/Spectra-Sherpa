import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import vueTsConfig from "@vue/eslint-config-typescript";
import skipFormatting from "@vue/eslint-config-prettier/skip-formatting";

export default [
  js.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  ...vueTsConfig(),
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
