"""Sauvegarde de Medigest au cabinet (tâche planifiée « Medigest - sauvegarde », midi et soir).

    C:\\Medigest\\venv\\Scripts\\python.exe C:\\Medigest\\app\\deploy\\sauvegarde.py

- Base : copie cohérente même serveur allumé (API backup de SQLite), vérifiée par
  integrity_check, dans sauvegardes\\base\\AAAA-MM-JJ_HHhMM.sqlite3. On garde les 90 dernières.
- Documents (PDF, photos) : miroir cumulatif dans sauvegardes\\documents (les fichiers ne
  sont jamais modifiés après dépôt : seuls les nouveaux sont copiés).
- Copie supplémentaire facultative : SAUVEGARDE_COPIE=E:\\Medigest dans medigest.env
  (disque USB, deuxième disque…). Absente ou débranchée : ignorée, sans erreur.
Code de sortie 0 si la sauvegarde principale a réussi.
"""
import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]  # C:\Medigest (deploy -> app -> Medigest)
BASE = RACINE / "donnees" / "db.sqlite3"
DOCUMENTS = RACINE / "donnees" / "media"
SAUVEGARDES = RACINE / "sauvegardes"
JOURNAL = RACINE / "logs" / "sauvegardes.log"
A_GARDER = 90


def journal(message):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    ligne = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(ligne + "\n")
    try:
        print(ligne)
    except (OSError, ValueError):  # tâche planifiée sans console
        pass


def lire_env():
    valeurs = {}
    fichier = RACINE / "medigest.env"
    if fichier.exists():
        for ligne in fichier.read_text(encoding="utf-8").splitlines():
            if "=" in ligne and not ligne.lstrip().startswith("#"):
                cle, valeur = ligne.split("=", 1)
                valeurs[cle.strip()] = valeur.strip()
    return valeurs


def copier_base(destination_dir):
    destination_dir.mkdir(parents=True, exist_ok=True)
    cible = destination_dir / f"{datetime.datetime.now():%Y-%m-%d_%Hh%M}.sqlite3"
    source = sqlite3.connect(BASE.as_uri() + "?mode=ro", uri=True)
    copie = sqlite3.connect(cible)
    with copie:
        source.backup(copie)
    source.close()
    etat = copie.execute("PRAGMA integrity_check").fetchone()[0]
    copie.close()
    if etat != "ok":
        cible.unlink(missing_ok=True)
        raise RuntimeError(f"copie de la base invalide ({etat})")
    anciennes = sorted(destination_dir.glob("*.sqlite3"))[:-A_GARDER]
    for ancienne in anciennes:
        ancienne.unlink()
    return cible


def copier_documents(destination_dir):
    nouveaux = 0
    if not DOCUMENTS.exists():
        return 0
    for fichier in DOCUMENTS.rglob("*"):
        if not fichier.is_file():
            continue
        cible = destination_dir / fichier.relative_to(DOCUMENTS)
        if cible.exists() and cible.stat().st_size == fichier.stat().st_size:
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fichier, cible)
        nouveaux += 1
    return nouveaux


def sauvegarder(dossier):
    copie = copier_base(dossier / "base")
    nouveaux = copier_documents(dossier / "documents")
    return copie, nouveaux


def main():
    if not BASE.exists():
        journal("ÉCHEC : base introuvable " + str(BASE))
        return 1
    try:
        copie, nouveaux = sauvegarder(SAUVEGARDES)
        journal(f"OK base -> {copie.name}, {nouveaux} nouveau(x) document(s)")
    except Exception as erreur:  # noqa: BLE001 — tout échec doit finir dans le journal
        journal(f"ÉCHEC sauvegarde principale : {erreur}")
        return 1

    supplementaire = lire_env().get("SAUVEGARDE_COPIE", "")
    if supplementaire:
        dossier = Path(supplementaire)
        if dossier.anchor and Path(dossier.anchor).exists():
            try:
                copie, nouveaux = sauvegarder(dossier)
                journal(f"OK copie supplémentaire -> {dossier}")
            except Exception as erreur:  # noqa: BLE001
                journal(f"ÉCHEC copie supplémentaire {dossier} : {erreur}")
        else:
            journal(f"Copie supplémentaire ignorée : {dossier} non branché")
    return 0


if __name__ == "__main__":
    sys.exit(main())
