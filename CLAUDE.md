# Medigest — Cabinet Dr ERRMILI Khadija (Gynécologie & Obstétrique)

Plateforme de gestion de cabinet médical. Django + templates HTML, HTMX, Alpine.js, Tailwind (CDN). Deux rôles strictement cloisonnés : **Médecin** et **Assistante**.

> **RÈGLE N°1 — DESIGN : lire `DESIGN.md` avant TOUT travail sur l'UI.**
> Ce fichier (CLAUDE.md) contient les règles projet. Le design system complet (tokens, composants, layout sidebar, motion, checklist qualité) vit dans **`DESIGN.md`**. Le plan de refonte écran par écran vit dans **`REDESIGN_PLAN.md`**. La maquette de référence validée est **`design_reference/dashboard_reference.html`** — c'est le niveau de finition attendu partout.

## 1. Architecture & Stack

- Django, apps dans `apps/` : `accounts`, `appointments`, `billing`, `clinical`, `communications`, `patients`, `common`.
- Templates dans `templates/` : `base.html` (config Tailwind + HTMX + Alpine + Lucide), puis un dossier par domaine (`assistant/`, `doctor/`, `patients/`, `billing/`, `pdf/`…). Les partials commencent par `_` et sont les cibles des swaps HTMX.
- Base SQLite (`db.sqlite3`), tests avec pytest (`run_tests.ps1`), démarrage via `start_cabinet.ps1`.
- Thème Tailwind : **source unique dans `static/js/tailwind-theme.js`** (utilisé par `base.html` en développement via le CDN, et par `tailwind.config.js` pour le CSS compilé du cabinet). **Tout nouveau token de design se déclare LÀ, jamais en valeur codée en dur dans un template.**
- Classes Tailwind uniquement dans `templates/` et `static/js/` (jamais construites dynamiquement, jamais dans le Python) : sinon elles manquent au cabinet.
- **Après toute modification de template ou du thème : `deploy\construire_css.ps1`** (recompile `static/vendor/medigest.css`). Le test `test_compiled_css_matches_templates` échoue tant que ce n'est pas fait.
- HTMX, Alpine, Lucide et la police sont servis depuis `static/vendor/` (versions figées) : aucune ressource externe, le cabinet doit fonctionner sans internet.

## 2. Workflow de travail (obligatoire)

1. **UI / refonte d'écran** → lire `DESIGN.md`, ouvrir la maquette de référence, puis suivre l'étape correspondante de `REDESIGN_PLAN.md`.
2. **Combinaison de skills OBLIGATOIRE pour toute refonte d'écran** (Assistante comme Médecin, sans exception) — les trois s'invoquent ensemble, pas au choix :
   - **`ui-ux-pro-max`** — structure de l'interface, patterns UX, hiérarchie de l'information.
   - **`Leonxlnx/taste-skill`** — finitions visuelles et raffinement (texture, détails, cohérence du rendu final).
   - **`vercel-labs/web-design-guidelines`** — espacement et hiérarchie type SaaS (grille, rythme vertical, densité).
   - Skills complémentaires selon le cas : `redesign-existing-projects` (reprise d'un écran déjà en place), `image-to-code` (reproduction fidèle d'une maquette/capture).
   - Le hook `impeccable` tourne automatiquement après chaque Edit/Write et au Stop — **corriger ses findings avant de conclure**, ne jamais les ignorer.
3. **MCP 21st.dev — source de composants obligatoire pour tout bloc complexe nouveau** : avant de construire une metric card, une table, un drawer ou tout autre bloc non trivial, interroger systématiquement le serveur MCP `21st.dev` pour des références de composants modernes, s'en inspirer visuellement, puis retranscrire à la main en Tailwind/HTMX conforme aux tokens de `DESIGN.md` — jamais de copier-coller de code React/shadcn brut dans ce projet Django/HTMX/Alpine.
4. **Toute modification de comportement** passe par les partials HTMX existants — pas de rechargement de page complet pour : statuts, encaissements, pagination, filtres, recherche.
5. **Vérification avant de conclure** : lancer le serveur, tester le parcours dans le navigateur (les deux rôles si l'écran est partagé), vérifier l'absence de layout shift et les états vides/chargement/erreur.

## 3. Règles d'Or UX & Interaction

- **Zéro rechargement inutile** : HTMX + Alpine.js pour statuts, encaissement, pagination, filtres, recherche.
- **Recherche instantanée** : debounce 250 ms, multi-critères (Nom, Prénom, Tél, CIN, N° Dossier).
- **Feedback immédiat** : chaque action → mise à jour visuelle optimiste + toast Alpine.js. Barre de progression HTMX globale déjà en place dans `base.html`.
- **Focus médical (fiche clinique médecin)** : DDR → âge gestationnel en SA calculé automatiquement ; modèles d'ordonnances en 1 clic ; sélection rapide des actes avec total dynamique.
- **Chaque écran doit avoir** : état vide soigné (illustration + phrase + action), état de chargement (skeleton, jamais de spinner plein écran), état d'erreur récupérable.

## 4. Sécurité & Cloisonnement des Données

- Séparation stricte Médecin / Assistante **côté serveur** (middleware + décorateurs) — jamais seulement dans le template.
- L'assistante encaisse et gère la file d'attente **sans AUCUN accès** aux données cliniques sensibles (diagnostics, observations, ordonnances).
- Génération PDF sécurisée (ordonnances, comptes rendus, reçus) avec archivage automatique — templates dans `templates/pdf/`.
- Aucune donnée patiente réelle dans les fixtures, captures ou commits.

## 5. Langue & Contenu

- Interface 100 % en français. Dates au format long français (« samedi 29 août 2026 »), montants en DH (« 250,00 DH »).
- Vocabulaire métier : patiente (féminin), RDV, encaissement, file d'attente, actes, DDR, SA.
- Micro-copie : ton calme et professionnel, jamais technique (« Aucune patiente pour le moment » plutôt que « 0 résultats »).

## 6. Interdits

- Couleur, ombre, rayon ou espacement en dur hors des tokens de `base.html` / `DESIGN.md`.
- Bleu/violet génériques « Tailwind par défaut » — la palette est le vert sauge et ses pastels médicaux définis dans `DESIGN.md`.
- Spinner plein écran, `alert()`, rechargement complet pour une action locale.
- Emoji en guise d'icône — uniquement Lucide (`stroke-width="1.75"`).
- Supprimer ou contourner le hook impeccable.

## 7. Installation au cabinet

- PC de l'assistante, dossier `C:\Medigest` (accès administrateurs uniquement) : `app\` (code), `donnees\` (base + documents), `sauvegardes\`, `logs\`, `medigest.env` (configuration, hors du code).
- Installation et mises à jour : `deploy\INSTALLER.cmd` depuis le projet téléchargé (session administrateur). Serveur Waitress en tâche planifiée « Medigest - serveur » (SYSTEM, au démarrage), sauvegardes « Medigest - sauvegarde » à 12h30 et 16h45.
- Versions de production figées dans `deploy/requirements-prod.txt`. **Toute modification d'un gabarit PDF (`templates/pdf/`) se teste avec ces versions exactes** (xhtml2pdf 0.2.17 place le texte autrement que les versions récentes) : venv dédié + `pip install -r deploy/requirements-prod.txt pytest pytest-django`, puis `pytest`. En A5 le texte est agrandi via la variable `a5` dans le bloc `<style>` unique de chaque gabarit (jamais un second bloc `<style>` : mal pris en compte par 0.2.17).
- Base neuve : `python manage.py installer_cabinet` crée le cabinet, les actes et les comptes (idempotent). Toute donnée de configuration du cabinet Errmili ajoutée par migration doit AUSSI être ajoutée à cette commande.
