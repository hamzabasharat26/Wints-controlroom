import type { Config } from "tailwindcss";

const config: Config = {
    content: [
        "./app/**/*.{js,ts,jsx,tsx,mdx}",
        "./components/**/*.{js,ts,jsx,tsx,mdx}",
    ],
    theme: {
        extend: {
            colors: {
                // Catppuccin Mocha palette
                base: "#11111b",
                mantle: "#181825",
                crust: "#1e1e2e",
                surface0: "#313244",
                surface1: "#45475a",
                overlay: "#6c7086",
                text: "#cdd6f4",
                subtext: "#a6adc8",
                blue: "#89b4fa",
                green: "#a6e3a1",
                red: "#f38ba8",
                yellow: "#f9e2af",
                orange: "#fab387",
                mauve: "#cba6f7",
                teal: "#94e2d5",
            },
            animation: {
                "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
                "fade-in": "fadeIn 0.4s ease-out",
                "slide-up": "slideUp 0.3s ease-out",
            },
            keyframes: {
                fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
                slideUp: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
            },
        },
    },
    plugins: [],
};

export default config;
