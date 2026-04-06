import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'dark-900': '#0d0d1a',
        'dark-800': '#1a1a2e',
        'dark-700': '#252540',
        'dark-600': '#2c2c4a',
        'dark-500': '#3d3d5c',
        'accent-red': '#c0392b',
        'accent-red-light': '#e74c3c',
        'accent-red-dark': '#7f1d1d',
        muted: '#8892a4',
        'text-primary': '#e8eaed',
        'text-secondary': '#b0b8c8',
        border: '#2c2c4a',
      },
      fontFamily: {
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-red': 'pulse-red 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fade-in 0.2s ease-out',
        'slide-in-left': 'slide-in-left 0.25s ease-out',
        'slide-in-right': 'slide-in-right 0.25s ease-out',
      },
      keyframes: {
        'pulse-red': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4', backgroundColor: '#c0392b' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-in-left': {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        'slide-in-right': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
      },
      boxShadow: {
        panel: '4px 0 24px rgba(0,0,0,0.6)',
        'panel-right': '-4px 0 24px rgba(0,0,0,0.6)',
        card: '0 2px 12px rgba(0,0,0,0.4)',
      },
    },
  },
  plugins: [],
};

export default config;
