/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Matches main ASTRA web app palette exactly
        navy: {
          950: '#020817',
          900: '#0e1654',
        },
        gold: {
          400: '#f5c842',
        },
        // Per-bank accent — change brand.800 to match the bank's primary colour
        brand: {
          800: '#6b21a8',  // KBL purple — swap for next bank
        },
      },
    },
  },
  plugins: [],
}
