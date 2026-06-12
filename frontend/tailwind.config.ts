import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: {
          night: '#1c1c1c',
          'night-soft': '#202020',
        },
        primary: {
          DEFAULT: '#3ecf8e',
          deep: '#24b47e',
          soft: '#4ade80',
        },
        ink: {
          DEFAULT: '#171717',
          mute: '#707070',
          'mute-2': '#9a9a9a',
          faint: '#b2b2b2',
        },
        hairline: {
          DEFAULT: '#2e2e2e',
          strong: '#3a3a3a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: [
          'ui-monospace',
          'Menlo',
          'Monaco',
          'Consolas',
          'Liberation Mono',
          'monospace',
        ],
      },
    },
  },
} satisfies Config
