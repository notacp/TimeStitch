import type { Config } from "tailwindcss";

const config: Config = {
    content: [
        "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
        "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
        "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    ],
    theme: {
        extend: {
            colors: {
                background: "var(--background)",
                foreground: "var(--foreground)",
                yt: {
                    red: "#FF0000",
                    black: "#0F0F0F",
                    gray: "#272727",
                    "light-gray": "#AAAAAA",
                }
            },
        },
    },
    plugins: [],
};
export default config;
