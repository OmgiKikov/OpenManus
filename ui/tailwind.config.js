module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#e6f7f4',
          100: '#ccefe9',
          200: '#99dfd3',
          300: '#66cfbd',
          400: '#33bfa7',
          500: '#00af91',
          600: '#008c74',
          700: '#006957',
          800: '#00463a',
          900: '#00231d',
        },
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
