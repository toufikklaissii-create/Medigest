from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import Patient


@login_required
def index(request):
    patients = Patient.objects.all()[:50]
    return render(request, "patients/index.html", {"patients": patients})


@login_required
def create_patient(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        if first_name and last_name:
            patient = Patient.objects.create(
                first_name=first_name,
                last_name=last_name,
                cin=request.POST.get("cin", "").strip(),
                birth_date=request.POST.get("birth_date") or None,
                phone=request.POST.get("phone", "").strip(),
                emergency_contact=request.POST.get("emergency_contact", "").strip(),
                blood_group=request.POST.get("blood_group", "").strip(),
                allergies=request.POST.get("allergies", "").strip(),
                medical_history=request.POST.get("medical_history", "").strip(),
            )
            messages.success(request, f"Patiente {patient} créée ({patient.patient_number}).")
            return redirect("appointments:create_appointment_for", patient_id=patient.pk)
        messages.error(request, "Nom et prénom sont obligatoires.")

    return render(request, "patients/create.html")
