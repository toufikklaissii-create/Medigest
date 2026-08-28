# Directives Système & Design System - Cabinet Médical Dr ERRMILI KHADIJA (Medigest)

## 1. Identité Visuelle & Tokens (« Clinique Apaisante » Haut de Gamme)
- **Palette Principale :**
  - Vert Sauge Médical (Primary) : 
    - `sauge-50`: `#F4F7F5` (surfaces actives)
    - `sauge-100`: `#E3ECE7` (bordures douces / tags)
    - `sauge-500`: `#52796F` (accents & boutons secondaires)
    - `sauge-600`: `#354F52` (boutons d'action principaux, focus)
    - `sauge-900`: `#2F3E46` (titres et forts contrastes)
  - Neutres & Surfaces :
    - `canvas`: `#FBFBFC` (fond général, jamais de blanc pur éblouissant)
    - `surface`: `#FFFFFF` (cartes, tiroirs, modals)
    - `border-subtle`: `#E2E8F0` / `#EAEBED` (bordures 1px chirurgicales)
    - `text-main`: `#0F172A` (ardoise sombre, lisibilité optimale)
    - `text-muted`: `#64748B` (métadonnées)
  - Statuts Pastel Médicaux :
    - Arrivée : `bg-amber-50 text-amber-700 border-amber-200`
    - En attente : `bg-sky-50 text-sky-700 border-sky-200`
    - En consultation : `bg-emerald-50 text-emerald-700 border-emerald-200`
    - Terminée : `bg-slate-50 text-slate-600 border-slate-200`
    - Alerte/Allergie/Urgence : `bg-rose-50 text-rose-700 border-rose-200`

- **Typographie & Éléments UI :**
  - Police : 'Plus Jakarta Sans' (Google Fonts).
  - Rayon des bordures : `rounded-xl` (12px pour cartes) et `rounded-2xl` (16px pour modals).
  - Ombres : Ultra-douces `shadow-sm` (`box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.03)`).
  - Icônes : Lucide Icons avec `stroke-width="1.75"`.

## 2. Références de Design & Standards d'Exécution
- **21st.dev :** Utiliser les composants UI modernes (metric cards, headers, drawers) via le serveur MCP.
- **Uiverse.io :** S'inspirer pour les micro-interactions élégantes (boutons tactiles, spinners de chargement discrets, toggles, badges animés subtils).
- **Bklit.com :** S'inspirer pour l'organisation aérée des tableaux de bord (padding généreux de 24px, hiérarchie claire, zéro encombrement visuel).
- **Awesome-Design-MD & Impeccable :** Appliquer systématiquement les contrôles de contraste, l'alignement typographique, les micro-transitions (`transition-all duration-150 ease-in-out`) et l'élimination de tout layout shift.

## 3. Règles d'Or UX & Interaction
- **Zéro Rechargement de Page Inutile :** Toutes les actions de changement de statut, d'encaissement, de pagination et de filtres utilisent HTMX et Alpine.js.
- **Recherche Instantanée :** Barre de recherche HTMX avec debounce 250ms multi-critères (Nom, Prénom, Tél, CIN, N° Dossier).
- **Feedback Immédiat :** Chaque action déclenche une mise à jour d'état visuelle immédiate et un toast de confirmation Alpine.js.
- **Focus Médical :** La fiche clinique du médecin doit permettre de renseigner les données d'un geste (DDR calculant automatiquement l'âge gestationnel en SA, modèles d'ordonnances en 1 clic, sélection rapide des actes avec total dynamique).

## 4. Sécurité & Cloisonnement des Données
- Séparation stricte des accès Médecin / Assistante côté serveur (middleware + décorateurs).
- L'assistante encaisse et gère la file d'attente sans AUCUN accès aux données cliniques sensibles (diagnostics, observations médicales, ordonnances).
- Génération PDF sécurisée pour les ordonnances, comptes rendus et reçus avec archivage automatique.
