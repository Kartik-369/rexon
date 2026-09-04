/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        rexon: {
          dark: '#0a0a0f',
          card: '#111118',
          border: '#1e1e2e',
          accent: '#6366f1',
          green: '#22c55e',
          amber: '#f59e0b',
          red: '#ef4444',
          muted: '#71717a',
        }
      }
    },
  },
  plugins: [],
}
