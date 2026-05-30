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
        arabic: ['Tajawal', 'sans-serif'],
      },
    },
  },
  darkMode: 'class',
  plugins: [
    heroui({
      defaultTheme: 'dark',
      themes: {
        dark: {
          extend: 'dark',
          colors: {
            background: '#020617',
            foreground: '#f8fafc',
            divider: '#1e293b',
            content1: '#0f172a',
            content2: '#1e293b',
            content3: '#334155',
            content4: '#475569',
            primary: {
              50:  '#eff6ff',
              100: '#dbeafe',
              200: '#bfdbfe',
              300: '#93c5fd',
              400: '#60a5fa',
              500: '#3b82f6',
              600: '#2563eb',
              700: '#1d4ed8',
              800: '#1e40af',
              900: '#1e3a8a',
              DEFAULT: '#3b82f6',
              foreground: '#ffffff',
            },
            success: {
              DEFAULT: '#22c55e',
              foreground: '#ffffff',
            },
            warning: {
              DEFAULT: '#f59e0b',
              foreground: '#ffffff',
            },
            danger: {
              DEFAULT: '#ef4444',
              foreground: '#ffffff',
            },
          },
        },
      },
    }),
  ],
}
