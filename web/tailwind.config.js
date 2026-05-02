/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  theme: {
    extend: {
      // Per Cluster 0 Chunk Plan §scope, branding is driven by CSS variables
      // written from /api/v2/system/firm-info on auth completion. Tailwind
      // utilities `bg-primary`, `text-accent` resolve to these variables so
      // components don't need to know about the firm-specific colour values.
      colors: {
        primary: 'var(--color-primary)',
        accent: 'var(--color-accent)',
      },
    },
  },
  plugins: [],
}
