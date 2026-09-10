# Saisie des constantes d'accueil par l'assistante — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the assistant capture Tension/Poids/Taille/DDR at patient intake (arrival/waiting), storing them on the `Consultation` row so the doctor sees them pre-filled and editable, without ever exposing clinical fields to the assistant role.

**Architecture:** Reuse the existing `Consultation` model unchanged. Add a small, self-contained "vitals" form partial (its own HTMX target, `hx-swap="outerHTML"` on itself) that can be embedded in two places: inside the existing calendar appointment drawer, and inside a new lightweight modal opened from a button on each kanban card in the assistant dashboard's queue board. One backend endpoint saves the four fields only; a second endpoint renders the modal for the kanban entry point.

**Tech Stack:** Django views/templates, HTMX (`hx-post`/`hx-get`, `HX-Trigger` toast header), Alpine.js (existing modal/drawer chrome patterns already in the codebase), pytest/Django `TestCase`.

---

## File Structure

- Modify: `apps/appointments/views.py` — add `_cabinet_doctor` helper, `save_intake_vitals` view, `intake_vitals_modal` view; add `consultation` to `appointment_drawer`'s context.
- Modify: `apps/appointments/urls.py` — 2 new routes.
- Create: `templates/assistant/_intake_vitals_form.html` — the reusable 4-field form (self-contained HTMX target via `data-intake-vitals-root`).
- Create: `templates/assistant/_intake_vitals_modal.html` — modal chrome wrapping the form partial (used from the kanban).
- Modify: `templates/assistant/_appointment_drawer_content.html` — embed the form partial when the appointment is active (arrived/waiting/in_consultation).
- Modify: `templates/assistant/_queue_board.html` — add a "Constantes" icon button per active card, opening the modal.
- Modify: `templates/assistant/dashboard.html` — add `<div id="modal-container"></div>`.
- Create: `tests/test_intake_vitals.py` — automated regression tests for the backend behavior.

Note on scope: the spec's suggestion to make whole kanban cards open the full calendar drawer was refined during implementation planning. The calendar drawer's other forms (`calendar_advance_status`, reschedule, cancel) all `hx-target="#calendar-body"`, which doesn't exist on the dashboard page — reusing the full drawer there would silently break those buttons. Instead, the kanban gets its own focused modal containing only the vitals form; the full drawer (with all its actions) stays calendar-only. This still satisfies "tiroir RDV — calendrier + kanban" from the approved design: the same vitals form partial is used in both places, just wrapped differently.

---

### Task 1: Backend — save/read vitals on `Consultation`

**Files:**
- Modify: `apps/appointments/views.py`
- Modify: `apps/appointments/urls.py`
- Test: `tests/test_intake_vitals.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_intake_vitals.py`:

```python
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class IntakeVitalsTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")

        self.doctor = User.objects.create_user(username="dr_vitals", password="testpass123")
        Profile.objects.update_or_create(
            user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet}
        )

        self.assistant = User.objects.create_user(username="assist_vitals", password="testpass123")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )

        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Salma", last_name="Vitals"
        )
        self.appointment = Appointment.objects.create(
            cabinet=self.cabinet,
            patient=self.patient,
            date=timezone.now(),
            status=Appointment.Status.WAITING,
        )

        self.client = Client()
        self.client.login(username="assist_vitals", password="testpass123")

    def test_assistant_creates_consultation_and_saves_vitals(self):
        response = self.client.post(
            reverse("appointments:save_intake_vitals", args=[self.appointment.pk]),
            {
                "blood_pressure": "12/8",
                "weight_kg": "68.5",
                "height_cm": "165",
                "last_menstrual_period": "2026-08-01",
            },
        )
        self.assertEqual(response.status_code, 200)

        consultation = Consultation.objects.get(appointment=self.appointment)
        self.assertEqual(consultation.doctor, self.doctor)
        self.assertEqual(consultation.blood_pressure, "12/8")
        self.assertEqual(str(consultation.weight_kg), "68.50")
        self.assertEqual(str(consultation.height_cm), "165.0")
        self.assertEqual(str(consultation.last_menstrual_period), "2026-08-01")

    def test_assistant_cannot_set_clinical_fields(self):
        self.client.post(
            reverse("appointments:save_intake_vitals", args=[self.appointment.pk]),
            {
                "blood_pressure": "12/8",
                "diagnostic": "Tentative d'injection de diagnostic",
                "clinical_notes": "Tentative d'injection de notes",
                "ultrasound_notes": "Tentative d'injection d'échographie",
            },
        )
        consultation = Consultation.objects.get(appointment=self.appointment)
        self.assertEqual(consultation.diagnostic, "")
        self.assertEqual(consultation.clinical_notes, "")
        self.assertEqual(consultation.ultrasound_notes, "")

    def test_second_save_updates_existing_consultation_without_duplicate(self):
        url = reverse("appointments:save_intake_vitals", args=[self.appointment.pk])
        self.client.post(url, {"blood_pressure": "12/8", "weight_kg": "68"})
        self.client.post(url, {"blood_pressure": "13/9", "weight_kg": "69"})

        self.assertEqual(Consultation.objects.filter(appointment=self.appointment).count(), 1)
        consultation = Consultation.objects.get(appointment=self.appointment)
        self.assertEqual(consultation.blood_pressure, "13/9")
        self.assertEqual(str(consultation.weight_kg), "69.00")

    def test_doctor_sees_prefilled_vitals(self):
        self.client.post(
            reverse("appointments:save_intake_vitals", args=[self.appointment.pk]),
            {"blood_pressure": "12/8", "weight_kg": "68", "height_cm": "165"},
        )
        doctor_client = Client()
        doctor_client.login(username="dr_vitals", password="testpass123")
        response = doctor_client.get(
            reverse("clinical:consultation_detail", args=[self.appointment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12/8")

    def test_no_doctor_in_cabinet_does_not_crash(self):
        empty_cabinet = Cabinet.objects.create(nom="Cabinet Vide", slug="cabinet-vide")
        assistant_no_doctor = User.objects.create_user(
            username="assist_alone", password="testpass123"
        )
        Profile.objects.update_or_create(
            user=assistant_no_doctor,
            defaults={"role": Profile.Role.ASSISTANT, "cabinet": empty_cabinet},
        )
        patient = Patient.objects.create(
            cabinet=empty_cabinet, first_name="Nadia", last_name="Solo"
        )
        appointment = Appointment.objects.create(
            cabinet=empty_cabinet,
            patient=patient,
            date=timezone.now(),
            status=Appointment.Status.ARRIVED,
        )
        client = Client()
        client.login(username="assist_alone", password="testpass123")

        response = client.post(
            reverse("appointments:save_intake_vitals", args=[appointment.pk]),
            {"blood_pressure": "12/8"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Consultation.objects.filter(appointment=appointment).exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv\Scripts\python.exe -m pytest tests/test_intake_vitals.py -v`
Expected: FAIL — `reverse()` raises `NoReverseMatch` for `appointments:save_intake_vitals` (URL doesn't exist yet).

- [ ] **Step 3: Add the backend views**

In `apps/appointments/views.py`, add these imports at the top (alongside the existing ones):

```python
from django.contrib.auth.models import User

from apps.accounts.models import Profile
from apps.clinical.models import Consultation
```

Add a helper function near the top-level helpers (after `_toast_header`, before `_today_appointments`):

```python
def _cabinet_doctor(cabinet):
    return User.objects.filter(
        profile__role=Profile.Role.DOCTOR, profile__cabinet=cabinet
    ).first()
```

Modify the existing `appointment_drawer` view (currently around line 288) to pass the linked consultation, if any:

```python
@login_required
def appointment_drawer(request, pk):
    """GET: renders the appointment detail drawer content."""
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"),
        pk=pk,
        cabinet=request.user.profile.cabinet,
    )
    consultation = Consultation.objects.filter(appointment=appointment).first()
    return render(
        request,
        "assistant/_appointment_drawer_content.html",
        {
            "appointment": appointment,
            "next_label": NEXT_STATUS_LABEL.get(appointment.status),
            "consultation": consultation,
        },
    )
```

Add two new views right after `appointment_drawer`:

```python
@login_required
def intake_vitals_modal(request, pk):
    """GET: renders the standalone 'Constantes d'accueil' modal for the kanban entry point."""
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"),
        pk=pk,
        cabinet=request.user.profile.cabinet,
    )
    consultation = Consultation.objects.filter(appointment=appointment).first()
    return render(
        request,
        "assistant/_intake_vitals_modal.html",
        {"appointment": appointment, "consultation": consultation},
    )


@login_required
def save_intake_vitals(request, pk):
    """POST: saves Tension/Poids/Taille/DDR onto the appointment's Consultation.

    Only ever touches these four intake fields — never clinical_notes,
    diagnostic, or ultrasound_notes — so this endpoint stays safe to expose
    to the assistant role regardless of caller.
    """
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=pk, cabinet=cabinet)
    consultation = Consultation.objects.filter(appointment=appointment).first()
    error_message = None

    if request.method == "POST":
        if consultation is None:
            doctor = _cabinet_doctor(cabinet)
            if doctor is None:
                error_message = (
                    "Aucun médecin n'est rattaché à ce cabinet : "
                    "impossible d'enregistrer les constantes."
                )
            else:
                consultation = Consultation.objects.create(
                    appointment=appointment,
                    patient=appointment.patient,
                    cabinet=cabinet,
                    doctor=doctor,
                )

        if consultation is not None:
            consultation.blood_pressure = request.POST.get("blood_pressure", "")
            consultation.weight_kg = request.POST.get("weight_kg") or None
            consultation.height_cm = request.POST.get("height_cm") or None
            consultation.last_menstrual_period = (
                request.POST.get("last_menstrual_period") or None
            )
            consultation.save(
                update_fields=[
                    "blood_pressure",
                    "weight_kg",
                    "height_cm",
                    "last_menstrual_period",
                ]
            )

    response = render(
        request,
        "assistant/_intake_vitals_form.html",
        {"appointment": appointment, "consultation": consultation},
    )
    if error_message:
        response.headers["HX-Trigger"] = _toast_header(error_message, "error")
    elif consultation is not None:
        response.headers["HX-Trigger"] = _toast_header(
            f"{appointment.patient} — constantes enregistrées."
        )
    return response
```

In `apps/appointments/urls.py`, add two routes right after the `appointment_drawer` line:

```python
    path("calendar/<int:pk>/drawer/", views.appointment_drawer, name="appointment_drawer"),
    path("calendar/<int:pk>/vitals/", views.save_intake_vitals, name="save_intake_vitals"),
    path("calendar/<int:pk>/vitals/modal/", views.intake_vitals_modal, name="intake_vitals_modal"),
```

(This replaces just the single existing `appointment_drawer` line — keep every other line in the file unchanged.)

- [ ] **Step 4: Create the vitals form partial referenced by the view**

Create `templates/assistant/_intake_vitals_form.html`:

```html
<div data-intake-vitals-root class="border-t border-border-subtle pt-4 mb-4">
    <p class="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2 flex items-center gap-1.5">
        <i data-lucide="activity" class="w-3.5 h-3.5" stroke-width="1.75"></i> Constantes d'accueil
    </p>
    <form hx-post="{% url 'appointments:save_intake_vitals' appointment.pk %}"
          hx-target="closest [data-intake-vitals-root]" hx-swap="outerHTML"
          class="grid grid-cols-2 gap-2.5">
        {% csrf_token %}
        <div>
            <label class="block text-[11px] font-medium text-text-muted mb-1">Tension (mmHg)</label>
            <input type="text" name="blood_pressure" value="{{ consultation.blood_pressure|default:'' }}" placeholder="12/8"
                   class="w-full rounded-lg border border-border-subtle px-2.5 py-2 text-sm transition-colors duration-150 hover:border-sauge-500/50 focus:outline-none focus:ring-2 focus:ring-sauge-500/40 focus:border-sauge-500">
        </div>
        <div>
            <label class="block text-[11px] font-medium text-text-muted mb-1">Poids (kg)</label>
            <input type="number" step="0.1" name="weight_kg" value="{{ consultation.weight_kg|default:'' }}"
                   class="w-full rounded-lg border border-border-subtle px-2.5 py-2 text-sm transition-colors duration-150 hover:border-sauge-500/50 focus:outline-none focus:ring-2 focus:ring-sauge-500/40 focus:border-sauge-500">
        </div>
        <div>
            <label class="block text-[11px] font-medium text-text-muted mb-1">Taille (cm)</label>
            <input type="number" step="0.1" name="height_cm" value="{{ consultation.height_cm|default:'' }}"
                   class="w-full rounded-lg border border-border-subtle px-2.5 py-2 text-sm transition-colors duration-150 hover:border-sauge-500/50 focus:outline-none focus:ring-2 focus:ring-sauge-500/40 focus:border-sauge-500">
        </div>
        <div>
            <label class="block text-[11px] font-medium text-text-muted mb-1">DDR</label>
            <input type="date" name="last_menstrual_period" value="{{ consultation.last_menstrual_period|date:'Y-m-d'|default:'' }}"
                   class="w-full rounded-lg border border-border-subtle px-2.5 py-2 text-sm transition-colors duration-150 hover:border-sauge-500/50 focus:outline-none focus:ring-2 focus:ring-sauge-500/40 focus:border-sauge-500">
        </div>
        <button type="submit"
                class="btn-tactile col-span-2 inline-flex items-center justify-center gap-1.5 text-sm font-semibold bg-sauge-600 text-white rounded-lg py-2.5 shadow-sm hover:bg-sauge-900">
            <i data-lucide="save" class="w-4 h-4" stroke-width="1.75"></i> Enregistrer les constantes
        </button>
    </form>
</div>
```

- [ ] **Step 5: Create the modal wrapper (needed for the `intake_vitals_modal` view to resolve)**

Create `templates/assistant/_intake_vitals_modal.html`:

```html
<div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm px-4"
     x-data="{ open: true }" x-show="open" x-cloak
     x-transition:enter="transition ease-out duration-150" x-transition:enter-start="opacity-0" x-transition:enter-end="opacity-100">
    <div @click.outside="open = false" @keydown.escape.window="open = false"
         x-trap="open"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0 scale-95"
         x-transition:enter-end="opacity-100 scale-100"
         class="bg-surface rounded-2xl shadow-popover border border-slate-200/70 w-full max-w-sm p-6 max-h-[90vh] overflow-y-auto">
        <div class="flex items-center justify-between mb-1">
            <h3 class="font-semibold text-text-main flex items-center gap-2">
                <span class="h-8 w-8 rounded-lg bg-sauge-50 text-sauge-600 flex items-center justify-center">
                    <i data-lucide="activity" class="w-4 h-4" stroke-width="1.75"></i>
                </span>
                Constantes d'accueil
            </h3>
            <button type="button" @click="open = false" class="btn-tactile inline-flex items-center justify-center h-8 w-8 rounded-full text-text-muted hover:text-rose-600 hover:bg-rose-50">
                <i data-lucide="x" class="w-4 h-4" stroke-width="1.75"></i>
            </button>
        </div>
        <p class="text-xs text-text-muted mb-1">{{ appointment.patient.first_name }} {{ appointment.patient.last_name }}</p>

        {% include "assistant/_intake_vitals_form.html" %}
    </div>
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv\Scripts\python.exe -m pytest tests/test_intake_vitals.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 7: Run the full test suite to check for regressions**

Run: `venv\Scripts\python.exe -m pytest -v`
Expected: PASS — `tests/test_full_flow.py` and `tests/test_intake_vitals.py` all green.

- [ ] **Step 8: Commit**

```bash
git add apps/appointments/views.py apps/appointments/urls.py templates/assistant/_intake_vitals_form.html templates/assistant/_intake_vitals_modal.html tests/test_intake_vitals.py
git commit -m "$(cat <<'EOF'
feat: assistante peut saisir Tension/Poids/Taille/DDR à l'accueil

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019Ec6puxsXaLdXA3bq5qvep
EOF
)"
```

---

### Task 2: Embed the vitals form in the calendar drawer

**Files:**
- Modify: `templates/assistant/_appointment_drawer_content.html`

- [ ] **Step 1: Add the vitals section to the drawer**

In `templates/assistant/_appointment_drawer_content.html`, insert the vitals include right after the reason paragraph (currently line 47: `<p class="text-sm text-text-main mb-5">{{ appointment.reason|default:"—" }}</p>`) and before the WhatsApp reminder block (currently line 49: `{% if appointment.whatsapp_reminder_link %}`):

```html
        <p class="text-sm text-text-main mb-5">{{ appointment.reason|default:"—" }}</p>

        {% if appointment.status == 'arrived' or appointment.status == 'waiting' or appointment.status == 'in_consultation' %}
        {% include "assistant/_intake_vitals_form.html" %}
        {% endif %}

        {% if appointment.whatsapp_reminder_link %}
```

Every other line in the file stays exactly as-is (the advance-status form, reschedule form, and cancel form keep their existing `#calendar-body` targets unchanged — they're only ever rendered from the calendar page, where `#calendar-body` exists).

- [ ] **Step 2: Start the dev server**

Run: `.\start_cabinet.ps1` (or, if already running from earlier in this session, skip this step and reuse it)

- [ ] **Step 3: Manually verify in the browser**

1. Log in as the assistant (`dr_errmili`/assistant seed user — check `apps/accounts/management/commands/seed_demo_data.py` for exact demo credentials).
2. Go to Planning/Agenda (`appointments:calendar`).
3. Click an appointment whose status is "Arrivée" or "En attente" (mark one via the kanban if none exists).
4. Confirm the drawer shows a "Constantes d'accueil" section with 4 empty fields.
5. Fill Tension/Poids/Taille/DDR, click "Enregistrer les constantes".
6. Confirm: a success toast appears, the drawer stays open, and the fields keep the values just entered (page did not reload).
7. Close and reopen the drawer for the same appointment — confirm the values are still pre-filled.
8. Open a "Terminée" (completed) or "Programmé" (scheduled, not yet arrived) appointment — confirm the vitals section does NOT appear.

- [ ] **Step 4: Commit**

```bash
git add templates/assistant/_appointment_drawer_content.html
git commit -m "$(cat <<'EOF'
feat: constantes d'accueil visibles dans le tiroir RDV du calendrier

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019Ec6puxsXaLdXA3bq5qvep
EOF
)"
```

---

### Task 3: Add the kanban entry point (queue board)

**Files:**
- Modify: `templates/assistant/_queue_board.html`
- Modify: `templates/assistant/dashboard.html`

- [ ] **Step 1: Add the modal container to the dashboard**

In `templates/assistant/dashboard.html`, add a modal container div right before the closing `{% endblock %}` (currently line 152, after the closing `</div>` of the 3-column grid on line 150):

```html
        </div>
    </div>

    <div id="modal-container"></div>

</div>
{% endblock %}
```

- [ ] **Step 2: Add the "Constantes" button to each active kanban card**

In `templates/assistant/_queue_board.html`, replace the card header block (currently lines 19-33):

```html
                <div class="flex items-start justify-between gap-2 mb-1">
                    <div class="flex items-center gap-2.5 min-w-0">
                        <div class="size-8 shrink-0 rounded-full bg-sauge-50 text-sauge-700 flex items-center justify-center text-xs font-bold">
                            {{ appt.patient.first_name|slice:":1" }}{{ appt.patient.last_name|slice:":1" }}
                        </div>
                        <p class="text-sm font-semibold text-text-main truncate">{{ appt.patient.first_name }} {{ appt.patient.last_name }}</p>
                    </div>
                    {% if status != 'completed' %}
                    <a href="{% url 'clinical:consultation_detail' appt.pk %}"
                       title="Ouvrir le dossier" aria-label="Ouvrir le dossier de {{ appt.patient.first_name }} {{ appt.patient.last_name }}"
                       class="btn-tactile shrink-0 inline-flex items-center justify-center text-text-muted hover:text-sauge-600 rounded-lg h-7 w-7">
                        <i data-lucide="folder-open" class="w-3.5 h-3.5" stroke-width="1.75"></i>
                    </a>
                    {% endif %}
                </div>
```

with:

```html
                <div class="flex items-start justify-between gap-2 mb-1">
                    <div class="flex items-center gap-2.5 min-w-0">
                        <div class="size-8 shrink-0 rounded-full bg-sauge-50 text-sauge-700 flex items-center justify-center text-xs font-bold">
                            {{ appt.patient.first_name|slice:":1" }}{{ appt.patient.last_name|slice:":1" }}
                        </div>
                        <p class="text-sm font-semibold text-text-main truncate">{{ appt.patient.first_name }} {{ appt.patient.last_name }}</p>
                    </div>
                    {% if status != 'completed' %}
                    <div class="flex items-center gap-1 shrink-0">
                        <button type="button"
                                hx-get="{% url 'appointments:intake_vitals_modal' appt.pk %}"
                                hx-target="#modal-container" hx-swap="innerHTML"
                                title="Constantes d'accueil" aria-label="Saisir les constantes de {{ appt.patient.first_name }} {{ appt.patient.last_name }}"
                                class="btn-tactile inline-flex items-center justify-center text-text-muted hover:text-sauge-600 rounded-lg h-7 w-7">
                            <i data-lucide="activity" class="w-3.5 h-3.5" stroke-width="1.75"></i>
                        </button>
                        <a href="{% url 'clinical:consultation_detail' appt.pk %}"
                           title="Ouvrir le dossier" aria-label="Ouvrir le dossier de {{ appt.patient.first_name }} {{ appt.patient.last_name }}"
                           class="btn-tactile inline-flex items-center justify-center text-text-muted hover:text-sauge-600 rounded-lg h-7 w-7">
                            <i data-lucide="folder-open" class="w-3.5 h-3.5" stroke-width="1.75"></i>
                        </a>
                    </div>
                    {% endif %}
                </div>
```

- [ ] **Step 3: Manually verify in the browser**

1. Log in as the assistant, go to the dashboard.
2. In the "File d'attente du jour" kanban, find a card in the "Arrivée" or "En attente" column.
3. Click the new activity icon button — confirm a centered modal opens titled "Constantes d'accueil" with the patient's name and the 4 fields.
4. Fill and save — confirm a success toast, and the modal's form updates in place (still open).
5. Click outside the modal or press Escape — confirm it closes cleanly.
6. Confirm the pre-existing "Ouvrir le dossier" icon and the "Marquer…" advance-status button still work exactly as before (no regression).
7. Confirm a card in the "Terminée" column has neither icon button (unchanged from before).

- [ ] **Step 4: Commit**

```bash
git add templates/assistant/_queue_board.html templates/assistant/dashboard.html
git commit -m "$(cat <<'EOF'
feat: bouton Constantes d'accueil sur les cartes de la file d'attente

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019Ec6puxsXaLdXA3bq5qvep
EOF
)"
```

---

### Task 4: End-to-end verification (doctor side + cloisonnement)

**Files:** none (verification only)

- [ ] **Step 1: Full manual walkthrough**

1. As the assistant: create/pick a patient, create today's appointment, advance it to "En attente" via the kanban.
2. Save Tension "12/7", Poids "70", Taille "168", DDR (a date ~10 weeks ago) via the kanban modal.
3. Advance the appointment to "En consultation".
4. Log in as the doctor, open that consultation (`clinical:doctor_dashboard` → the patient's card → "Ouvrir le dossier" or direct link).
5. Confirm: Tension/Poids/Taille inputs are pre-filled with the assistant's values and are still editable; the DDR field shows the same date and the "Terme (calcul auto)" box already shows a computed SA + jours value without the doctor doing anything.
6. Edit one field (e.g. adjust Poids) and validate the consultation — confirm save works as before (no regression to the existing doctor flow).

- [ ] **Step 2: Confirm cloisonnement still holds**

1. As the assistant, attempt to `GET` `clinical:doctor_dashboard` directly (e.g. via URL bar) — confirm still `403 Accès refusé`.
2. Confirm the assistant's kanban modal and calendar drawer never render `clinical_notes`, `diagnostic`, or `ultrasound_notes` anywhere (visually inspect — they were never added to `_intake_vitals_form.html`, so this should already hold).

- [ ] **Step 3: Run the full automated suite one last time**

Run: `venv\Scripts\python.exe -m pytest -v`
Expected: PASS, no regressions.

- [ ] **Step 4: Update the spec doc if any deviation occurred during implementation**

If Task 3's kanban-modal-instead-of-full-drawer refinement is the only deviation from `docs/superpowers/specs/2026-09-10-saisie-constantes-assistante-design.md`, no spec edit is required (already called out in this plan's File Structure note). If anything else changed, update that spec file to match reality and commit.

---

## Notes for the executor

- This codebase has no `forms.py` layer for these views — request.POST is read directly, matching the existing style in `apps/clinical/views.py::consultation_detail` and `apps/appointments/views.py`. Stay consistent with that.
- `Consultation.weight_kg` / `height_cm` are `DecimalField`; assigning a plain string from `request.POST.get(...)` works the same way the existing `clinical/views.py::consultation_detail` view already does it — no casting needed beyond what's shown above.
- Do not add `role_required` decorators to the new views — every other calendar/drawer view in this file is plain `@login_required`, and adding role gating here would be an unrelated scope change.
