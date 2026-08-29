# Medigest — Cabinet Dr ERRMILI Khadija (Gynécologie & Obstétrique)

Plateforme de gestion de cabinet médical. Django + templates HTML, HTMX, Alpine.js, Tailwind (CDN). Deux rôles strictement cloisonnés : **Médecin** et **Assistante**.

> **RÈGLE N°1 — DESIGN : lire `DESIGN.md` avant TOUT travail sur l'UI.**
> Ce fichier (CLAUDE.md) contient les règles projet. Le design system complet (tokens, composants, layout sidebar, motion, checklist qualité) vit dans **`DESIGN.md`**. Le plan de refonte écran par écran vit dans **`REDESIGN_PLAN.md`**. La maquette de référence validée est **`design_reference/dashboard_reference.html`** — c'est le niveau de finition attendu partout.

## 1. Architecture & Stack

- Django, apps dans `apps/` : `accounts`, `appointments`, `billing`, `clinical`, `communications`, `patients`, `common`.
- Templates dans `templates/` : `base.html` (config Tailwind + HTMX + Alpine + Lucide), puis un dossier par domaine (`assistant/`, `doctor/`, `patients/`, `billing/`, `pdf/`…). Les partials commencent par `_` et sont les cibles des swaps HTMX.
- Base SQLite (`db.sqlite3`), tests avec pytest (`run_tests.ps1`), démarrage via `start_cabinet.ps1`.
- Tailwind est configuré inline dans `base.html` (`tailwind.config`) : **tout nouveau token de design se déclare LÀ, jamais en valeur codée en dur dans un template.**

## 2. Workflow de travail (obligatoire)

1. **UI / refonte d'écran** → lire `DESIGN.md`, ouvrir la maquette de référence, puis suivre l'étape correspondante de `REDESIGN_PLAN.md`.
2. **Skills à invoquer selon la tâche :**
   - Refonte / création d'écran : `ui-ux-pro-max` (recherche de patterns), `web-design-guidelines`, `design-taste-frontend`, `high-end-visual-design`.
   - Reprise d'un écran existant : `redesign-existing-projects`.
   - Reproduction d'une maquette/capture : `image-to-code`.
   - Le hook `impeccable` tourne automatiquement après chaque Edit/Write et au Stop — **corriger ses findings avant de conclure**, ne jamais les ignorer.
3. **Toute modification de comportement** passe par les partials HTMX existants — pas de rechargement de page complet pour : statuts, encaissements, pagination, filtres, recherche.
4. **Vérification avant de conclure** : lancer le serveur, tester le parcours dans le navigateur (les deux rôles si l'écran est partagé), vérifier l'absence de layout shift et les états vides/chargement/erreur.

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
