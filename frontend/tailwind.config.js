import { heroui } from '@heroui/react'

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    './node_modules/@heroui/theme/dist/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        arabic: ['Cairo', 'sans-serif'],
        cairo:  ['Cairo', 'sans-serif'],
      },
    },
  },
  darkMode: 'class',
  plugins: [
    heroui({
      defaultTheme: 'light',
      themes: {
        // ── Purity-style light theme (teal accent) ──────────────────────────
        light: {
          extend: 'light',
          colors: {
            background: '#f8f9fe',   // soft airy page bg
            foreground: '#2d3748',   // slate-700 body text
            divider:    '#e2e8f0',   // soft borders
            content1:   '#ffffff',   // cards
            content2:   '#f7fafc',   // subtle insets
            content3:   '#edf2f7',
            content4:   '#e2e8f0',
            // Teal primary (Purity accent)
            primary: {
              50:  '#f0fdfa',
              100: '#ccfbf1',
              200: '#99f6e4',
              300: '#5eead4',
              400: '#2dd4bf',
              500: '#14b8a6',
              600: '#0d9488',
              700: '#0f766e',
              800: '#115e59',
              900: '#134e4a',
              DEFAULT: '#14b8a6',
              foreground: '#ffffff',
            },
            secondary: {
              DEFAULT: '#06b6d4',   // cyan complement
              foreground: '#ffffff',
            },
            success: { DEFAULT: '#16a34a', foreground: '#ffffff' },
            warning: { DEFAULT: '#d97706', foreground: '#ffffff' },
            danger:  { DEFAULT: '#e53e3e', foreground: '#ffffff' },
            default: {
              50:  '#f7fafc',
              100: '#edf2f7',
              200: '#e2e8f0',
              300: '#cbd5e0',
              400: '#a0aec0',
              500: '#718096',
              600: '#4a5568',
              700: '#2d3748',
              800: '#1a202c',
              900: '#171923',
            },
          },
        },
        // Dark theme kept for users who prefer it (no longer default)
        dark: {
          extend: 'dark',
          colors: {
            background: '#020917',
            foreground: '#f1f5f9',
            divider: '#1c2d42',
            content1: '#0c1627',
            content2: '#111e32',
            content3: '#1c2d42',
            content4: '#2d4060',
            primary: {
              DEFAULT: '#14b8a6',
              foreground: '#ffffff',
            },
            secondary: { DEFAULT: '#06b6d4', foreground: '#ffffff' },
            success: { DEFAULT: '#22c55e', foreground: '#ffffff' },
            warning: { DEFAULT: '#f59e0b', foreground: '#ffffff' },
            danger:  { DEFAULT: '#ef4444', foreground: '#ffffff' },
          },
        },
      },
    }),
  ],
}
