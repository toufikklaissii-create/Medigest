# DESIGN.md — Design System Medigest « Clinique Apaisante » v3 (Premium SaaS épuré)

Référence unique pour toute l'UI. Objectif : le niveau de finition d'un produit SaaS haut de gamme, épuré et ultra-moderne (Linear, Attio, Cron, **bklit.com**) appliqué à un cabinet médical — calme, précis, chirurgical. La maquette validée est `design_reference/dashboard_reference.html` : **tout écran refondu doit atteindre ce niveau**.

## 0. Principes (à relire avant chaque écran)

1. **Calme clinique** : beaucoup d'air, peu d'encre. On enlève avant d'ajouter.
2. **Hiérarchie par la typographie et l'espace**, pas par les bordures. Une seule bordure 1px subtile suffit ; jamais de double encadrement (carte dans carte encadrée).
3. **La couleur signifie quelque chose** : le sauge = action et identité ; les pastels = statuts médicaux ; tout le reste est neutre. Jamais de couleur décorative gratuite.
4. **Chaque interaction répond** : hover, active, focus-visible, loading, empty, error — les 6 états existent sur chaque composant interactif.
5. **Zéro layout shift** : les swaps HTMX remplacent des blocs de dimensions stables ; les images/icônes ont des dimensions explicites ; les skeletons ont la taille du contenu final.

### Références d'inspiration officielles

- **[bklit.com](https://bklit.com)** — standard absolu pour les layouts aérés : cartes sans bordure lourde, padding généreux **24px minimum**, ombres très douces type `shadow-sm`/`shadow-card`, zéro encombrement visuel, hiérarchie claire par l'espace plutôt que par l'encadrement. À consulter avant toute refonte de grille de cartes ou de tableau de bord.
- **[uiverse.io](https://uiverse.io)** — référence obligatoire pour le comportement des éléments interactifs : hovers fluides, `active:scale-[0.98]` (retour tactile), loaders discrets (jamais de spinner plein écran), boutons avec micro-feedback. À consulter avant toute refonte de bouton, toggle, ou état de chargement.
- `design_reference/dashboard_reference.html` reste la maquette de référence pixel pour la densité et la respiration globale de l'app.

## 1. Fondations

### 1.1 Palette (tokens Tailwind — déclarés dans `base.html`)

```js
colors: {
  sauge: {
    25:  "#F8FAF9",   // fonds de section très légers
    50:  "#F4F7F5",   // surfaces actives, hover subtil
    100: "#E3ECE7",   // bordures douces, tags, fond sidebar active
    200: "#C9D8D0",   // bordures accent, séparateurs marqués
    400: "#6B9080",   // icônes secondaires, graphiques
    500: "#52796F",   // accents, boutons secondaires, liens
    600: "#354F52",   // boutons d'action principaux, focus ring
    700: "#2E4345",
    900: "#2F3E46",   // titres, sidebar sombre
    950: "#25333A",   // fond sidebar (bas de dégradé)
  },
  canvas:  "#F7F8F8",   // fond général de l'app (légèrement plus profond que v1 pour faire "flotter" les cartes)
  surface: "#FFFFFF",   // cartes, tiroirs, modals
  "surface-raised": "#FFFFFF",
  "border-subtle": "#E7EAEE", // bordure 1px par défaut
  "border-strong": "#D8DDE3",
  "text-main":  "#101828",
  "text-soft":  "#475467",
  "text-muted": "#667085",
  "text-faint": "#98A2B3",  // placeholders, méta discrètes
}
```

**Statuts pastel médicaux** (inchangés, à appliquer via composant badge, jamais à la main) :

| Statut | Classes |
|---|---|
| Arrivée | `bg-amber-50 text-amber-700 border-amber-200` (dot `bg-amber-400`) |
| En attente | `bg-sky-50 text-sky-700 border-sky-200` (dot `bg-sky-400`) |
| En consultation | `bg-emerald-50 text-emerald-700 border-emerald-200` (dot `bg-emerald-400`) |
| Terminée | `bg-slate-50 text-slate-600 border-slate-200` (dot `bg-slate-400`) |
| Alerte / Allergie / Urgence | `bg-rose-50 text-rose-700 border-rose-200` (dot `bg-rose-500`) |

### 1.2 Typographie

- **UNIQUE typographie autorisée sur l'ensemble du projet** : `Plus Jakarta Sans` (400 / 500 / 600 / 700 / 800). Aucune police Serif, aucune police d'affichage alternative. Cette règle s'applique sans exception aux titres de page (H1), aux grands chiffres des KPI, aux badges, et à tout le corps de texte.
- **Interdiction explicite** : `Fraunces` et toute autre police Serif sont **bannies** du projet (voir §6 Anti-patterns). Une interface médicale premium se construit par la hiérarchie de graisse, de taille et d'espace — pas par un changement de famille de police.
- Échelle : H1 page `text-[28px] leading-tight font-semibold` · chiffres KPI `text-4xl font-bold` · H2 section `text-[15px] font-semibold tracking-[0.01em]` · corps `text-sm` (14px) · méta `text-[13px] text-text-muted` · micro-labels `text-[11px] font-semibold uppercase tracking-[0.08em] text-text-faint`. Toute la hiérarchie ci-dessus est en `Plus Jakarta Sans`, seule la graisse (`font-weight`) et la taille varient.
- Chiffres tabulaires partout où des montants/heures s'alignent : `font-variant-numeric: tabular-nums`.

### 1.3 Espacement, rayons, ombres

Référence directrice : **bklit.com** — layouts aérés, cartes sans bordure lourde, padding généreux.

- Grille d'espacement 4px ; padding interne des cartes **24px minimum** (`p-6`) ; gouttières de grille `gap-5` ou `gap-6` ; sections séparées par `mt-10`.
- Rayons : boutons/inputs `rounded-lg` (10px) · cartes `rounded-2xl` (16px) · modals/tiroirs `rounded-2xl` · badges `rounded-full`.
- Ombres (déjà dans `base.html`) : cartes `shadow-card`, popovers/menus `shadow-popover` — toujours **très douces** (`shadow-sm` à défaut), jamais d'ombre dure. Le relief vient surtout du contraste `canvas` ↔ `surface`, pas de la bordure.
- Focus : `focus-visible:ring-2 ring-sauge-600/30 ring-offset-2` — sur TOUT élément interactif.

### 1.4 Iconographie

Lucide uniquement, `stroke-width="1.75"`, taille 16px dans le texte/boutons, 18–20px dans la sidebar et les en-têtes de carte. Icône de carte dans une pastille `size-9 rounded-lg bg-sauge-50 text-sauge-600 grid place-items-center`.

## 2. Layout — Sidebar fixe (nouvelle structure)

Remplace la top-nav par onglets. Structure cible de `base.html` :

```
┌──────────┬──────────────────────────────────────────┐
│ SIDEBAR  │ TOPBAR (h-16, transparent sur canvas)    │
│ 264px    ├──────────────────────────────────────────┤
│ fixe     │ CONTENU  max-w-[1200px] mx-auto px-8 py-8│
└──────────┴──────────────────────────────────────────┘
```

- **Sidebar** : `w-[264px]`, fond dégradé sombre `bg-gradient-to-b from-sauge-900 to-sauge-950`, texte `text-white/70`. En haut : logo + « Cabinet Dr ERRMILI Khadija / Gynécologie & Obstétrique ». Navigation : Accueil, Planning, Patientes, Facturation, Communications (icônes Lucide 18px + label). Item actif : `bg-white/10 text-white rounded-lg` + barre d'accent 3px `bg-sauge-400` à gauche. Hover : `bg-white/5`, transition 150ms (référence **uiverse.io** pour la fluidité du hover). En bas : carte utilisateur (avatar initiales, rôle « Assistante » ou « Dr ERRMILI ») + bouton Déconnexion.
- **Topbar** : date du jour en toutes lettres, badge « Live » (dot `bg-emerald-400` + `animate-pulse` discret), recherche globale (Cmd/Ctrl+K), actions contextuelles de la page à droite.
- **Contenu** : chaque page commence par un en-tête : H1 `Plus Jakarta Sans` `font-semibold` + sous-titre `text-text-muted` à gauche, boutons d'action à droite. Jamais plus d'un bouton primaire visible par écran.
- Responsive : < 1024px la sidebar se replie en rail d'icônes 64px (tooltips), < 768px elle devient un tiroir off-canvas Alpine.

## 3. Composants (contrats à respecter partout)

### 3.1 Boutons

Référence directrice : **uiverse.io** pour tout le comportement interactif ci-dessous.

- **Primaire** : `bg-sauge-600 text-white rounded-lg px-4 h-10 text-sm font-semibold shadow-sm hover:bg-sauge-700 active:scale-[0.98] transition-all duration-150` + icône 16px optionnelle.
- **Secondaire** : `bg-surface border border-border-subtle text-text-main hover:bg-sauge-25 hover:border-sauge-200`.
- **Ghost** : `text-text-soft hover:bg-slate-100/70 hover:text-text-main`.
- **Destructif** : réservé aux confirmations — `bg-rose-600` uniquement dans un modal de confirmation.
- État loading : le label est remplacé par un spinner 16px discret + le bouton garde SA LARGEUR (`min-w` figée). Jamais de spinner plein écran, jamais de loader intrusif.

### 3.2 Cartes KPI (dashboard)
`bg-surface rounded-2xl border border-border-subtle shadow-card p-6` (padding 24px minimum, cf. §1.3/bklit.com) ; pastille icône en haut à gauche ; badge de contexte (« jour », « à faire ») en haut à droite ; **chiffre en Plus Jakarta Sans `font-bold text-4xl`** ; label `text-[13px] text-text-muted`. Hover : `translate-y-[-2px] shadow-popover` 150ms. Si la valeur demande une action (encaissements en attente > 0), la carte entière est cliquable et route vers l'écran concerné.

### 3.3 File d'attente (kanban 4 colonnes)
Colonnes = zones `bg-slate-50/60 rounded-2xl p-3` avec en-tête (dot statut + titre + compteur `rounded-full bg-white`). Cartes patientes : `bg-surface rounded-xl border border-border-subtle p-4 shadow-sm`, nom en 600, heure + motif en méta, avatar initiales `bg-sauge-100 text-sauge-700`. Changement de statut : bouton d'action contextuelle (« Installer », « Débuter », « Clôturer ») → HTMX swap de la colonne + toast. La carte qui arrive dans une colonne anime `animate-[slide-in_200ms_ease-out]`.

### 3.4 Badges de statut
Composant unique (include `_status_badge.html`) : `inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium` (Plus Jakarta Sans, comme partout) + dot `size-1.5 rounded-full`. Jamais de badge recodé à la main.

### 3.5 Tableaux (patientes, facturation)
En-tête `text-[11px] uppercase tracking-[0.08em] text-text-faint bg-slate-50/50 sticky top-0` ; lignes `h-14 border-b border-border-subtle hover:bg-sauge-25 transition-colors` ; montants alignés à droite en tabular-nums ; actions de ligne dans un menu `…` (popover Alpine). Pagination HTMX en pied, jamais de rechargement.

### 3.6 Formulaires
Label `text-[13px] font-medium text-text-soft mb-1.5` ; input `h-10 rounded-lg border-border-subtle bg-white focus:border-sauge-500 focus:ring-2 focus:ring-sauge-600/20 placeholder:text-text-faint` ; erreur : bordure `border-rose-300` + message `text-[13px] text-rose-600 mt-1` (jamais seulement une couleur). Groupes espacés de `space-y-5`. Champs monétaires et téléphone avec masque léger Alpine.

### 3.7 Modals & tiroirs (drawers)
Modal : overlay `bg-sauge-950/30 backdrop-blur-[2px]`, panneau `rounded-2xl max-w-lg shadow-popover`, entrée `opacity+scale(0.97)→1` 180ms, sortie 120ms. Drawer (fiche RDV, détails) : glisse depuis la droite `w-[420px]`, même overlay. Fermeture : clic overlay, Échap, bouton X. Focus piégé dans le panneau (x-trap).

### 3.8 Toasts
En bas à droite, `bg-sauge-900 text-white rounded-xl px-4 py-3 shadow-popover`, icône statut, auto-dismiss 3,5s, empilement max 3. Succès = check sauge-400 ; erreur = `bg-rose-600`.

### 3.9 États vides
Toujours : icône Lucide 24px dans pastille `bg-slate-100`, phrase humaine (« Aucune patiente pour le moment »), et si pertinent une action (« + Nouveau RDV »). Centré verticalement dans son conteneur, `py-10` minimum.

### 3.10 Skeletons
Blocs `bg-slate-100 rounded animate-pulse` aux dimensions EXACTES du contenu final (`hx-indicator`). Jamais de spinner plein écran (référence **uiverse.io** pour des loaders discrets à la place).

### 3.11 Calendrier / Planning
Grille horaire : lignes `border-border-subtle`, heure courante marquée par un filet `bg-rose-400` + dot. Événements : `rounded-lg border-l-[3px]` couleur du statut, fond pastel correspondant, heure + nom + motif. Mini-calendrier : jour sélectionné `bg-sauge-600 text-white rounded-full`, jours avec RDV : dot sauge sous le chiffre. Drag pour créer/déplacer si déjà supporté, sinon clic → drawer.

## 4. Motion

Référence directrice : **uiverse.io** pour l'ensemble des micro-interactions ci-dessous.

- Durées : micro (hover, active) **150ms** · entrées (modal, toast, colonne) **180–220ms** · jamais > 300ms. Easing `cubic-bezier(0.4, 0, 0.2, 1)` ; entrées avec léger `ease-out`.
- `transition-all duration-150 ease-in-out` par défaut sur l'interactif ; `motion-reduce:transition-none` respecté.
- Retour tactile systématique sur les boutons : `active:scale-[0.98]`.
- Les swaps HTMX utilisent `hx-swap="... swap:150ms settle:150ms"` + classe `.htmx-settling` pour un fondu doux — pas d'apparition brutale.
- Nombre qui change (KPI, total dynamique) : transition de type count-up courte (Alpine) ou fondu, jamais de saut sec.

## 5. Accessibilité & qualité (checklist de sortie d'écran)

- [ ] Contraste AA : texte ≥ 4.5:1, UI ≥ 3:1 (vérifier les pastels sur blanc).
- [ ] Navigation clavier complète + `focus-visible` visible partout ; focus piégé dans modals/drawers.
- [ ] Cibles tactiles ≥ 40px ; `aria-label` sur les boutons icône seule.
- [ ] 6 états présents : default / hover / active / focus / loading / empty / error.
- [ ] Aucun layout shift au chargement ni après swap HTMX.
- [ ] Textes français corrects (accents, pluriels « patientes »), montants « 1 250,00 DH », dates longues.
- [ ] Une seule police sur tout l'écran : `Plus Jakarta Sans`, aucune trace de Serif/Fraunces.
- [ ] Hook impeccable : zéro finding restant.
- [ ] Comparaison côte à côte avec `design_reference/dashboard_reference.html` : densité, respiration et finitions équivalentes.

## 6. Anti-patterns (à éliminer)

- **Police Serif ou Fraunces sur tout élément de l'interface** — abandonnée depuis la v3. `Plus Jakarta Sans` est l'unique typographie du projet, y compris pour les titres et les grands chiffres de KPI.
- Grandes zones vides encadrées qui « flottent » sans hiérarchie → les colonnes vides de la file d'attente doivent être compactes (hauteur mini) et s'étendre seulement avec du contenu.
- Cartes KPI muettes → chaque KPI actionnable est cliquable.
- Double bordure + ombre sur le même élément ; bordures 2px ; gris Tailwind par défaut mélangés aux tokens ; ombres dures (contraire à la référence bklit.com).
- Boutons primaires multiples dans un même écran ; libellés vagues (« Valider ») → verbes métier (« Encaisser », « Installer en salle »).
- Micro-interactions absentes ou brutales (changement d'état sans transition, hover sec) — contraire à la référence uiverse.io.
- Login : la carte doit être posée sur un fond travaillé (dégradé radial sauge très léger + motif discret), logo animé au chargement, bouton pleine largeur.
