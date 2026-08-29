# REDESIGN_PLAN.md — Refonte Medigest, écran par écran

Plan d'exécution pour Claude Code. Chaque étape = une session courte, un commit. **Toujours lire `DESIGN.md` d'abord** et comparer le résultat à `design_reference/dashboard_reference.html` avant de conclure. Le hook impeccable doit être vert à chaque étape.

## Règle d'or technique (non négociable)

> **Le design sublime l'interface, il ne casse jamais ce qui la fait fonctionner.**

Sur CHAQUE fichier touché, avant de conclure une étape :

- **Aucun attribut HTMX ne peut être supprimé, renommé ou altéré** : `hx-get`, `hx-post`, `hx-put`, `hx-swap`, `hx-target`, `hx-trigger`, `hx-push-url`, `hx-confirm`, `hx-indicator` — tous doivent survivre à l'identique. Seules les classes CSS et le markup de présentation autour peuvent changer.
- **Aucune balise de template Django ne peut être cassée** : `{% block %}`, `{% if %}`, `{% for %}`, `{% url %}`, `{% include %}`, `{% csrf_token %}`, les variables `{{ ... }}`. Un template qui ne parse plus (`get_template()` en échec) est un échec de l'étape, quelle que soit la qualité visuelle obtenue.
- **Aucune directive Alpine.js ne peut être perdue** : `x-data`, `x-show`, `x-model`, `@click`, `@submit`, `x-trap`, `x-transition`. Le raffinement visuel (Tailwind, transitions, `active:scale-[0.98]`) s'ajoute autour de ces directives, jamais à leur place.
- **Aucune logique serveur ne peut être modifiée** pendant une étape de design (vues, permissions, cloisonnement de rôle) — sauf ajout d'un contexte minime strictement nécessaire à l'affichage (ex. un agrégat déjà lisible ajouté au contexte d'une vue), jamais une règle métier.
- En cas de doute : `get_template()` sur le fichier + `manage.py check` doivent passer avant tout commit, et le parcours réel (navigateur, les deux rôles si l'écran est partagé) doit être rejoué pour confirmer qu'aucun swap HTMX n'est cassé.

## Ordre & dépendances

| # | Étape | Fichiers principaux | Skills à invoquer |
|---|---|---|---|
| 0 | Fondations (tokens + fonts) | `templates/base.html` | web-design-guidelines |
| 1 | Layout sidebar | `templates/base.html` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines |
| 2 | Login | `templates/accounts/login.html` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines |
| 3 | Dashboard assistante | `templates/assistant/dashboard.html` + partials `_queue_board`, `_pending_invoices`, `_today_list`, `_j2_reminders` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines (+ image-to-code depuis la maquette) — MCP 21st.dev pour les metric cards |
| 4 | Planning / calendrier | `templates/assistant/calendar.html` + `_calendar_*` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines |
| 5 | Patientes (liste + fiche + création) | `templates/patients/*` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines — MCP 21st.dev pour la table |
| 6 | Facturation | `templates/billing/index.html` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines — MCP 21st.dev pour la table |
| 7 | Espace médecin | `templates/doctor/dashboard.html`, `consultation.html` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines |
| 8 | Communications + tâches | `templates/communications/*` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines |
| 9 | Modals, drawers, toasts (passe transverse) | tous les partials `_*` | ui-ux-pro-max, Leonxlnx/taste-skill, web-design-guidelines — MCP 21st.dev pour les drawers |
| 10 | Passe finale qualité | tout | impeccable (audit), verification |

Sur les étapes 1 à 9 (tout écran Assistante ou Médecin), la combinaison **`ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines`** s'invoque systématiquement, ensemble — ce n'est pas une liste au choix (cf. CLAUDE.md §2). `redesign-existing-projects` et `image-to-code` s'ajoutent seulement quand le cas s'y prête (reprise d'un écran déjà en place / reproduction fidèle d'une capture).

## Étape 0 — Fondations (30 min)

Prompt à coller dans Claude Code :

> Lis DESIGN.md. Dans `templates/base.html` : (1) confirme que `Plus Jakarta Sans` est l'unique famille déclarée dans `fontFamily` (aucune police Serif/display) ; (2) mets à jour `tailwind.config` avec la palette étendue de DESIGN.md §1.1 (sauge 25→950, canvas #F7F8F8, text-soft/faint, border-strong) en gardant les alias legacy ; (3) ajoute les keyframes `slide-in` et la classe `.htmx-settling` de fondu ; (4) `tabular-nums` sur `body`. Ne touche à aucun template d'écran. Vérifie que le site s'affiche toujours correctement.

## Étape 1 — Layout sidebar (le plus structurant)

> Invoque `ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines`. Lis DESIGN.md §2. Refonds `templates/base.html` : sidebar fixe 264px (dégradé sauge-900→950, logo + nom du cabinet, nav Accueil/Planning/Patientes/Facturation/Communications avec item actif à barre d'accent, carte utilisateur + déconnexion en bas), topbar allégée (date longue, badge Live, actions de page via block), contenu `max-w-[1200px] mx-auto px-8 py-8`. Responsive : rail 64px < 1024px, drawer off-canvas Alpine < 768px. Les blocks Django existants (`{% block content %}` etc.) doivent continuer de fonctionner sur tous les écrans sans les modifier. **Aucun `hx-*`, aucune directive Alpine existante ne doit disparaître.**

## Étape 2 — Login

> Invoque `ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines`. Lis DESIGN.md. Refonds `templates/accounts/login.html` en écran signature : fond canvas avec dégradé radial sauge très subtil, carte `rounded-2xl shadow-card` centrée, logo dans pastille sauge-600 avec entrée animée douce, titre en `Plus Jakarta Sans` `font-semibold`, inputs conformes §3.6 avec icônes Lucide, bouton primaire pleine largeur avec état loading discret (référence uiverse.io), message d'erreur d'authentification stylé (pas de liste Django brute).

## Étape 3 — Dashboard assistante (écran vitrine)

> Invoque `ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines`, et interroge le MCP **21st.dev** pour 2-3 références de metric cards modernes avant de construire les KPI (inspiration visuelle uniquement, retranscription à la main en Tailwind). Lis DESIGN.md et ouvre `design_reference/dashboard_reference.html` : reproduis ce niveau exact. Refonds `templates/assistant/dashboard.html` et ses partials : en-tête de page (H1 `Plus Jakarta Sans` + sous-titre + actions), 4 KPI conformes §3.2 (chiffres en `Plus Jakarta Sans` `font-bold text-4xl`, cartes actionnables cliquables, padding 24px min. — référence bklit.com), recherche patiente proéminente, file d'attente kanban §3.3 avec colonnes compactes à vide, panneaux Facturation / RDV du jour / Rappels WhatsApp J+2 / Tâches en grille équilibrée. Conserve TOUS les attributs hx-* et les ids ciblés par HTMX ; états vides §3.9 et skeletons §3.10 partout.

## Étape 4 — Planning / calendrier

> Invoque `ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines`. Lis DESIGN.md §3.11. Refonds `calendar.html` + partials `_calendar_*` : mini-calendrier raffiné (jour actif rond sauge, dots RDV), vue jour avec filet « maintenant », événements à bordure gauche colorée par statut, toggle Vue jour / Vue mois en segmented control, création de RDV via drawer §3.7. Filtres par statut en badges cliquables, swap HTMX sans layout shift.

## Étapes 5–8 — Domaines

Même méthode pour Patientes, Facturation, Espace médecin, Communications :

> Invoque `ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines` (interroge le MCP 21st.dev pour la table ou le composant complexe concerné avant de le construire). Lis DESIGN.md. Refonds [écran] en appliquant les contrats de composants (§3) : tableaux §3.5 avec hover et menu de ligne, formulaires §3.6, badges via `_status_badge.html`, états vides/chargement. Spécifique médecin : fiche consultation = colonne clinique (DDR→SA auto, observations, ordonnances 1 clic) + colonne actes avec total dynamique animé ; densité un cran plus élevée mais même calme visuel. Ne modifie aucune logique serveur ni aucun cloisonnement de rôle.

## Étape 9 — Passe transverse interactions

> Invoque `ui-ux-pro-max` + `Leonxlnx/taste-skill` + `web-design-guidelines` (MCP 21st.dev pour le pattern de drawer). Unifie modals, drawers et toasts sur les contrats DESIGN.md §3.7–3.8 : un seul composant toast Alpine global, un seul pattern de drawer, animations d'entrée/sortie, focus piégé (`x-trap`), Échap. Supprime tout doublon de code d'overlay.

## Étape 10 — Passe finale qualité

> Parcours la checklist DESIGN.md §5 écran par écran (les deux rôles). Corrige tous les findings impeccable. Vérifie : contrastes AA, clavier, layout shift, textes français, cohérence des espacements, **une seule police (`Plus Jakarta Sans`) sur tout l'écran**. Produis un rapport des écarts restants.

## Règles de session

- Une étape = un commit (`git commit -m "design: étape N — ..."`). Ne jamais mélanger deux étapes.
- Jamais de modification de logique métier/serveur pendant la refonte (sauf ajout d'un partial ou d'un context minime pour l'UI).
- Si un choix visuel n'est pas couvert par DESIGN.md → s'aligner sur la maquette de référence, puis documenter la décision dans DESIGN.md.
- Le respect de la **Règle d'or technique** ci-dessus prime sur toute considération esthétique : un écran magnifique qui casse un `hx-swap` ou un `{% block %}` n'est pas terminé.
