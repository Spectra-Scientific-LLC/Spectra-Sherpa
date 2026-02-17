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
      // Phase A: disable rules that would cause mass failures
      "@typescript-eslint/no-explicit-any": "off",
      "vue/multi-word-component-names": "off",
      // PrimeVue uses camelCase props (optionLabel, scrollHeight, etc.)
      "vue/attribute-hyphenation": "off",
      // Cosmetic template ordering — not enforced in Phase A
      "vue/attributes-order": "off",
      // Phase A: unused-vars off — tighten in Phase B after cleanup
      "@typescript-eslint/no-unused-vars": "off",
      // Vue prop/template rules — tighten in Phase B
      "vue/no-required-prop-with-default": "off",
      "vue/no-template-shadow": "off",
    },
  },
  { ignores: ["dist/", "node_modules/"] },
];
