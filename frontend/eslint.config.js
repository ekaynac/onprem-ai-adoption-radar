import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist", "coverage", "src/api/generated"],
  },
  ...tseslint.configs.recommended,
);
