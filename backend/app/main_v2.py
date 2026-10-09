
from datetime import datetime
from pathlib import Path
import json
import re
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# ==================================================
# MEDGUARD API
# ==================================================

app = FastAPI(
    title="MedGuard API",
    description="Medication safety screening and report management",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================================================
# DATABASE
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "medguard.db"


def get_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                allergies TEXT DEFAULT '',
                conditions TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_name TEXT NOT NULL,
                medication_count INTEGER NOT NULL,
                risk_count INTEGER NOT NULL,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


initialize_database()


# ==================================================
# REQUEST MODELS
# ==================================================

class PatientInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=0, le=120)
    allergies: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class MedicationInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dose: str = Field(default="", max_length=100)
    frequency: str = Field(default="", max_length=100)


class AnalysisInput(BaseModel):
    patient: PatientInput
    medications: list[MedicationInput] = Field(default_factory=list)


class PrescriptionInput(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


# ==================================================
# MEDICINE NAMES
# Limited dictionary for text extraction.
# Not a comprehensive medication database.
# ==================================================

KNOWN_MEDICINES = [
    "acetaminophen",
    "amoxicillin",
    "amlodipine",
    "aspirin",
    "atorvastatin",
    "clopidogrel",
    "ibuprofen",
    "insulin",
    "metformin",
    "naproxen",
    "omeprazole",
    "paracetamol",
    "penicillin",
    "warfarin",
]

MEDICINE_ALIASES = {
    "acetaminophen": "paracetamol",
    "paracetamol": "paracetamol",
}


def normalize_medicine_name(name: str) -> str:
    name = " ".join(name.lower().strip().split())
    return MEDICINE_ALIASES.get(name, name)


def split_stored_list(value):
    return [item for item in (value or "").split("|") if item]


# ==================================================
# HEALTH CHECKS
# ==================================================

@app.get("/")
def home():
    return {
        "status": "ok",
        "application": "MedGuard",
        "message": "MedGuard backend is running",
    }


@app.get("/api/health")
def health():
    with get_connection() as connection:
        connection.execute("SELECT 1").fetchone()

    return {
        "status": "healthy",
        "database": "connected",
    }


# ==================================================
# PATIENT MANAGEMENT
# ==================================================

@app.get("/api/patients")
def get_patients():
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM patients ORDER BY id DESC"
        ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "age": row["age"],
            "allergies": split_stored_list(row["allergies"]),
            "conditions": split_stored_list(row["conditions"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.post("/api/patients")
def create_patient(patient: PatientInput):
    name = patient.name.strip()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="Patient name cannot be empty.",
        )

    allergies = [
        item.strip()
        for item in patient.allergies
        if item.strip()
    ]
    conditions = [
        item.strip()
        for item in patient.conditions
        if item.strip()
    ]
    created_at = datetime.now().isoformat(timespec="seconds")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO patients
                (name, age, allergies, conditions, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                patient.age,
                "|".join(allergies),
                "|".join(conditions),
                created_at,
            ),
        )
        patient_id = cursor.lastrowid

    return {
        "success": True,
        "message": "Patient profile saved",
        "id": patient_id,
    }


# ==================================================
# PRESCRIPTION TEXT EXTRACTION
# Keyword matching only; no OCR or AI diagnosis.
# ==================================================

@app.post("/api/prescription/extract")
def extract_prescription(data: PrescriptionInput):
    text = data.text.lower()
    found = []

    for medicine in KNOWN_MEDICINES:
        pattern = r"\b" + re.escape(medicine) + r"\b"

        if re.search(pattern, text):
            found.append({
                "name": medicine.title(),
                "dose": "",
                "frequency": "",
            })

    return {
        "success": True,
        "medications_found": len(found),
        "medications": found,
        "notice": (
            "Keyword-based extraction only. Verify medicine names, "
            "doses, and instructions against the original prescription."
        ),
    }


# ==================================================
# MEDICATION SCREENING
# Limited illustrative rules; not clinically validated.
# ==================================================

@app.post("/api/analyze")
def analyze_medications(data: AnalysisInput):
    patient = data.patient
    medications = data.medications

    names = [m.name.strip() for m in medications]
    normalized = [normalize_medicine_name(n) for n in names]
    risks = []

    def add_risk(severity, title, reason, related_medicines):
        risks.append({
            "severity": severity,
            "title": title,
            "reason": reason,
            "medications": related_medicines,
        })

    # 1. Duplicate names and explicitly defined aliases.
    groups = {}

    for name, normalized_name in zip(names, normalized):
        groups.setdefault(normalized_name, []).append(name)

    for matching_names in groups.values():
        if len(matching_names) > 1:
            add_risk(
                "MEDIUM",
                "Possible duplicate medicine",
                (
                    "These entries have the same normalized name or "
                    "a recognized alias: "
                    + ", ".join(matching_names)
                    + ". Verify ingredients, strengths, and instructions "
                    "with a qualified professional."
                ),
                matching_names,
            )

    # 2. Limited warfarin interaction flag.
    bleeding_medicines = {"ibuprofen", "naproxen", "aspirin"}

    if (
        "warfarin" in normalized
        and any(n in bleeding_medicines for n in normalized)
    ):
        related = [
            name for name, norm in zip(names, normalized)
            if norm == "warfarin" or norm in bleeding_medicines
        ]

        add_risk(
            "HIGH",
            "Potential bleeding interaction",
            (
                "Warfarin combined with certain pain relievers, including "
                "NSAIDs and aspirin, can increase bleeding risk. This "
                "limited rule is not a complete interaction check. Seek "
                "review from a doctor or pharmacist."
            ),
            related,
        )

    # 3. Kidney-condition reminder for selected medicines.
    kidney_condition = any(
        "kidney" in condition.lower()
        for condition in patient.conditions
    )

    kidney_medicines = [
        name for name, norm in zip(names, normalized)
        if norm in {"ibuprofen", "naproxen"}
    ]

    if kidney_condition and kidney_medicines:
        add_risk(
            "HIGH",
            "Medication review recommended for kidney disease",
            (
                "Some anti-inflammatory medicines may worsen kidney "
                "function in susceptible patients. A qualified professional "
                "should review the medication and medical history."
            ),
            kidney_medicines,
        )

    # 4. Limited allergy-name matching.
    for allergy in patient.allergies:
        allergy_norm = normalize_medicine_name(allergy)

        if not allergy_norm:
            continue

        for name, medicine_norm in zip(names, normalized):
            matches = allergy_norm == medicine_norm

            if (
                allergy_norm in {"penicillin", "penicillins"}
                and medicine_norm == "amoxicillin"
            ):
                matches = True

            if matches:
                add_risk(
                    "HIGH",
                    "Possible medication-allergy conflict",
                    (
                        f"The recorded allergy '{allergy}' may be relevant "
                        f"to '{name}'. This simple matching rule cannot "
                        "establish clinical cross-reactivity or safety. "
                        "Obtain professional review."
                    ),
                    [name],
                )

    # 5. Multiple medication review reminder.
    if len(medications) >= 5:
        add_risk(
            "MEDIUM",
            "Multiple medications require review",
            (
                f"{len(medications)} medication entries were submitted. "
                "A professional medication review may help identify "
                "interactions, duplicates, and monitoring needs."
            ),
            names,
        )

    # 6. Older patient review reminder.
    if patient.age >= 65 and len(medications) >= 4:
        add_risk(
            "MEDIUM",
            "Additional medication review may be appropriate",
            (
                "Age and the number of medication entries can be reasons "
                "to review the complete medication list, medical history, "
                "and doses with a qualified professional."
            ),
            names,
        )

    analyzed_at = datetime.now().isoformat(timespec="seconds")

    report = {
        "patient_name": patient.name.strip(),
        "patient_age": patient.age,
        "analyzed_at": analyzed_at,
        "medication_count": len(medications),
        "medications": [
            {
                "name": m.name,
                "dose": m.dose,
                "frequency": m.frequency,
            }
            for m in medications
        ],
        "risk_count": len(risks),
        "risks": risks,
        "notice": (
            "MedGuard is a limited medication-screening prototype. Its "
            "rules are not clinically validated and do not cover every "
            "medicine, dose, condition, or interaction. No warnings does "
            "not mean a medication combination is safe. Confirm prescriptions "
            "with a qualified doctor or pharmacist."
        ),
    }

    # Save report history.
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO reports
                (patient_name, medication_count, risk_count,
                 report_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient.name.strip(),
                len(medications),
                len(risks),
                json.dumps(report),
                analyzed_at,
            ),
        )

    return report


# ==================================================
# REPORT HISTORY
# ==================================================

@app.get("/api/reports")
def get_reports():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, patient_name, medication_count,
                   risk_count, report_json, created_at
            FROM reports
            ORDER BY id DESC
            """
        ).fetchall()

    results = []

    for row in rows:
        try:
            report_data = json.loads(row["report_json"])
        except (json.JSONDecodeError, TypeError):
            report_data = {}

        results.append({
            "id": row["id"],
            "patient_name": row["patient_name"],
            "medication_count": row["medication_count"],
            "risk_count": row["risk_count"],
            "created_at": row["created_at"],
            "report": report_data,
        })

    return results



# ==================================================
# PATIENT UPDATE / DELETE AND REPORT DELETE
# ==================================================

@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: int, patient: PatientInput):
    name = patient.name.strip()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="Patient name cannot be empty.",
        )

    allergies = [i.strip() for i in patient.allergies if i.strip()]
    conditions = [i.strip() for i in patient.conditions if i.strip()]

    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE patients
            SET name = ?, age = ?, allergies = ?, conditions = ?
            WHERE id = ?
            """,
            (
                name,
                patient.age,
                "|".join(allergies),
                "|".join(conditions),
                patient_id,
            ),
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Patient not found.")

    return {"success": True, "message": "Patient profile updated"}


@app.delete("/api/patients/{patient_id}")
def delete_patient(patient_id: int):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM patients WHERE id = ?", (patient_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Patient not found.")

    return {"success": True, "message": "Patient deleted"}


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: int):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM reports WHERE id = ?", (report_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Report not found.")

    return {"success": True, "message": "Report deleted"}
