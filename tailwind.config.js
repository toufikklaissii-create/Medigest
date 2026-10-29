// Compilation du CSS du cabinet (deploy\construire_css.ps1) : sans internet, sans CDN.
// Le thème est lu dans static/js/tailwind-theme.js, le même fichier que le mode développement.
// Les classes Tailwind ne s'écrivent QUE dans templates/ et static/js/ (voir apps/common/css_sources.py).
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, "static", "js", "tailwind-theme.js"), "utf8"), sandbox);

module.exports = {
    content: ["./templates/**/*.html", "./static/js/**/*.js"],
    theme: { extend: sandbox.window.MEDIGEST_TAILWIND_THEME },
};
