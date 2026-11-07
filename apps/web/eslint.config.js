import js from '@eslint/js';
import pluginSecurity from 'eslint-plugin-security';
import babelParser from '@babel/eslint-parser';

export default [
  js.configs.recommended,
  pluginSecurity.configs.recommended,
  {
    files: ['src/**/*.{js,jsx,ts,tsx}'],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: {
          presets: [
            ['@babel/preset-react', { runtime: 'automatic' }],
            ['@babel/preset-typescript', { ignoreExtensions: true }],
          ],
        },
      },
    },
    rules: {
      'no-unused-vars': 'off',
      'no-undef': 'off',
      'no-control-regex': 'off',
      'security/detect-object-injection': 'off',
    },
  },
  {
    ignores: ['dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**', '*.config.*'],
  },
];
