# Saisie des constantes d'accueil par l'assistante — design

Date : 2026-09-10

## Contexte

Aujourd'hui, la Tension, le Poids, la Taille et la DDR sont saisis par le
médecin dans `templates/doctor/consultation.html`, sur le champ `Consultation`
correspondant (`apps/clinical/models.py`). Le modèle `Consultation` possède déjà
les champs `blood_pressure`, `weight_kg`, `height_cm`, `last_menstrual_period`,
et la page médecin calcule déjà l'âge gestationnel (SA) côté client (Alpine.js)
à partir de la DDR.

Objectif : déplacer la **saisie initiale** de ces constantes vers le rôle
Assistante, au moment de l'accueil de la patiente (pointage "Arrivée" /
"En attente"), sans donner à l'assistante accès aux données cliniques
sensibles (diagnostic, notes d'échographie, ordonnances).

## Décisions

- **Pas de changement de modèle.** On réutilise `Consultation` tel quel.
- **Emplacement UI** : le tiroir de détail du rendez-vous
  (`templates/assistant/_appointment_drawer_content.html`), qui existe déjà et
  est utilisé depuis le calendrier (`assistant/calendar.html`) et sera rendu
  accessible aussi depuis les cartes du kanban "file d'attente"
  (`assistant/_queue_board.html`) sur le dashboard assistante.
- Le formulaire de constantes n'apparaît que lorsque le statut du RDV est
  `arrived`, `waiting`, ou `in_consultation` — la patiente doit être
  physiquement présente pour que la saisie ait un sens.
- **Attribution automatique du médecin** : comme le champ `Consultation.doctor`
  est obligatoire (`on_delete=PROTECT`, non nullable) et qu'un cabinet n'a
  qu'un seul médecin, la `Consultation` créée par l'assistante est rattachée
  au médecin du cabinet via
  `User.objects.filter(profile__role=Profile.Role.DOCTOR, profile__cabinet=cabinet).first()`
  (même pattern que `apps/communications/views.py::create_task`).
- **Cloisonnement des données** : le nouvel endpoint ne touche jamais
  `clinical_notes`, `diagnostic`, `ultrasound_notes` — uniquement les 4 champs
  d'accueil. La séparation est appliquée côté serveur (dans la vue), pas
  seulement dans le template.

## Backend

Nouvelle vue `apps/appointments/views.py::save_intake_vitals(request, pk)` :

- `POST` uniquement.
- Récupère le RDV : `get_object_or_404(Appointment, pk=pk, cabinet=request.user.profile.cabinet)`.
- `Consultation.objects.get_or_create(appointment=appointment, defaults={"patient": appointment.patient, "cabinet": cabinet, "doctor": <médecin du cabinet>})`.
- Met à jour `blood_pressure`, `weight_kg`, `height_cm`, `last_menstrual_period`
  à partir de `request.POST`, puis `consultation.save(update_fields=[...])`.
- Si aucun médecin n'est trouvé pour le cabinet (cas limite), la création de la
  consultation est refusée avec un message d'erreur (toast) plutôt que de
  planter — cas très improbable en pratique (cabinet à un seul médecin déjà
  seedé) mais on ne doit pas casser le flux d'accueil.
- Ré-affiche `assistant/_appointment_drawer_content.html` avec un toast de
  succès via `HX-Trigger` (`"{patient} — constantes enregistrées."`).

Nouvelle URL dans `apps/appointments/urls.py` :
`path("calendar/<int:pk>/vitals/", views.save_intake_vitals, name="save_intake_vitals")`.

`appointment_drawer` (vue existante) doit aussi passer la `Consultation` liée
au RDV (ou `None`) dans le contexte, pour pré-remplir le formulaire :
```python
consultation = getattr(appointment, "consultation", None)
```

## Frontend

### `templates/assistant/_appointment_drawer_content.html`

Ajouter une section "Constantes d'accueil" (affichée seulement si
`appointment.status in ('arrived', 'waiting', 'in_consultation')`) :

- Tension (`<input type="text" name="blood_pressure">`, placeholder `12/8`)
- Poids (`<input type="number" step="0.1" name="weight_kg">`, kg)
- Taille (`<input type="number" step="0.1" name="height_cm">`, cm)
- DDR (`<input type="date" name="last_menstrual_period">`)

Valeurs pré-remplies depuis `consultation.*` si la consultation existe déjà.
Formulaire : `hx-post="{% url 'appointments:save_intake_vitals' appointment.pk %}"`,
`hx-target` sur le conteneur racine du tiroir lui-même (le tiroir se
réaffiche in place, reste ouvert — contrairement aux formulaires "changer de
statut" / "annuler" qui ferment le tiroir après succès).

### `templates/assistant/dashboard.html`

Ajouter `<div id="drawer-container"></div>` (comme dans `calendar.html`).

### `templates/assistant/_queue_board.html`

Rendre chaque carte (statuts non `completed`) cliquable :
`hx-get="{% url 'appointments:appointment_drawer' appt.pk %}" hx-target="#drawer-container" hx-swap="innerHTML"`,
en cohérence avec le comportement déjà existant dans `_calendar_day.html`.
Le bouton "Ouvrir le dossier" (lien direct vers `clinical:consultation_detail`,
réservé au rôle médecin) et le bouton "avancer le statut" restent inchangés et
ne doivent pas déclencher l'ouverture du tiroir (`@click.stop` si nécessaire).

## Côté médecin

`templates/doctor/consultation.html` affiche et permet déjà l'édition de
`blood_pressure`, `weight_kg`, `height_cm`, `last_menstrual_period`, avec calcul
automatique de l'âge gestationnel (SA) en Alpine.js à partir de la DDR. Comme
ces champs proviennent du même objet `Consultation`, les valeurs saisies par
l'assistante apparaissent pré-remplies et restent modifiables — aucune
modification de ce template n'est nécessaire au-delà d'une vérification
manuelle.

## Permissions

- `save_intake_vitals` et `appointment_drawer` restent en `@login_required`
  simple (pas de `role_required`), cohérent avec le reste des vues du
  calendrier assistant aujourd'hui. La portée est limitée au `cabinet` de
  l'utilisateur connecté.
- Le cloisonnement clinique est garanti par le fait que la vue ne lit/écrit
  jamais les champs cliniques sensibles, indépendamment du rôle de
  l'utilisateur qui l'appelle.

## Tests / vérification

Pas de test automatisé unitaire prévu pour ce ticket (flux HTMX simple sur
modèle existant). Vérification manuelle :

1. Connexion assistante → dashboard → kanban "file d'attente".
2. Marquer une patiente "Arrivée" puis "En attente".
3. Cliquer sur la carte → le tiroir s'ouvre avec le formulaire "Constantes
   d'accueil" vide.
4. Saisir Tension/Poids/Taille/DDR → Enregistrer → toast de succès, tiroir
   reste ouvert, valeurs conservées.
5. Refaire le test depuis le calendrier (`assistant/calendar.html`) sur le
   même RDV → les valeurs déjà saisies apparaissent pré-remplies.
6. Connexion médecin → ouvrir la consultation du jour pour cette patiente →
   Tension/Poids/Taille/DDR pré-remplis, SA calculé automatiquement, champs
   toujours modifiables.
7. Vérifier qu'aucun champ clinique (diagnostic, notes, ordonnance) n'est
   visible ni modifiable depuis l'espace assistante.

## Hors périmètre

- Historique des constantes dans le temps (une seule valeur par consultation
  du jour, pas de série temporelle).
- Alerte clinique sur valeurs anormales (tension élevée, etc.) — pas demandé.
- Modification du modèle `Patient` ou `Appointment`.
