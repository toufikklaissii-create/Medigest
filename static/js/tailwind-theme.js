// Thème Tailwind de Medigest : SOURCE UNIQUE des tokens de design.
// Utilisé par base.html (mode développement, Tailwind CDN) ET par tailwind.config.js
// (CSS compilé pour le cabinet, sans internet). Tout nouveau token se déclare ICI.
window.MEDIGEST_TAILWIND_THEME = {
    colors: {
        // Palette de marque du cabinet : variables CSS injectées par
        // apps.accounts.context_processors.brand (sauge par défaut).
        sauge: {
            25: "rgb(var(--brand-25) / <alpha-value>)",
            50: "rgb(var(--brand-50) / <alpha-value>)",
            100: "rgb(var(--brand-100) / <alpha-value>)",
            200: "rgb(var(--brand-200) / <alpha-value>)",
            400: "rgb(var(--brand-400) / <alpha-value>)",
            500: "rgb(var(--brand-500) / <alpha-value>)",
            600: "rgb(var(--brand-600) / <alpha-value>)",
            700: "rgb(var(--brand-700) / <alpha-value>)",
            900: "rgb(var(--brand-900) / <alpha-value>)",
            950: "rgb(var(--brand-950) / <alpha-value>)",
        },
        canvas: "rgb(var(--brand-25) / <alpha-value>)",
        surface: "#FFFFFF",
        "surface-raised": "#FFFFFF",
        "border-subtle": "#E7EAEE",
        "border-strong": "#D8DDE3",
        "text-main": "#101828",
        "text-soft": "#475467",
        "text-muted": "#667085",
        "text-faint": "#98A2B3",
        // Legacy aliases kept so any un-migrated markup stays on-palette.
        primary: {
            DEFAULT: "rgb(var(--brand-600) / <alpha-value>)",
            dark: "rgb(var(--brand-900) / <alpha-value>)",
            light: "rgb(var(--brand-100) / <alpha-value>)",
        },
        cream: "#FBFBFC",
        border: "#E2E8F0",
        ink: {
            DEFAULT: "#0F172A",
            soft: "#64748B",
        },
    },
    fontFamily: {
        sans: ["Plus Jakarta Sans", "ui-sans-serif", "system-ui", "sans-serif"],
    },
    boxShadow: {
        soft: "0 2px 12px -2px rgba(30, 41, 59, 0.06)",
        sm: "0 1px 2px 0 rgb(0 0 0 / 0.03)",
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 8px 24px -12px rgb(15 23 42 / 0.08)",
        popover: "0 12px 32px -8px rgb(15 23 42 / 0.14), 0 4px 10px -4px rgb(15 23 42 / 0.08)",
    },
    keyframes: {
        "slide-in": {
            "0%": { opacity: 0, transform: "translateY(4px)" },
            "100%": { opacity: 1, transform: "none" },
        },
        "logo-in": {
            "0%": { opacity: 0, transform: "scale(0.85)" },
            "100%": { opacity: 1, transform: "scale(1)" },
        },
    },
    animation: {
        "slide-in": "slide-in 220ms cubic-bezier(0.4, 0, 0.2, 1)",
        "logo-in": "logo-in 500ms cubic-bezier(0.4, 0, 0.2, 1)",
    },
};
