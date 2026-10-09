from datetime import datetime
from pathlib import Path
import re
import sqlite3

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# --------------------------------------------------
# MEDGUARD - Medication Safety Prototype
# --------------------------------------------------

app = FastAPI(
    title="MedGuard API",
    description="Hackathon prototype for medication safety screening",
    version="1.0.0",
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


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

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


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class PatientInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    age: int = Field(ge=0, le=120)
    allergies: list[str] = []
    conditions: list[str] = []


class MedicationInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dose: str = ""
    frequency: str = ""


class AnalysisInput(BaseModel):
    patient: PatientInput
    medications: list[MedicationInput]


class PrescriptionInput(BaseModel):
    text: str = Field(min_length=1)


# --------------------------------------------------
# DEMO MEDICINE DICTIONARY
# This is a limited keyword list, not a clinical database.
# --------------------------------------------------

KNOWN_MEDICINES = [
    "warfarin",
    "ibuprofen",
    "amoxicillin",
    "penicillin",
    "metformin",
    "aspirin",
    "paracetamol",
    "acetaminophen",
    "atorvastatin",
    "amlodipine",
    "omeprazole",
    "insulin",
    "naproxen",
    "clopidogrel",
]


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "status": "ok",
        "application": "MedGuard",
        "message": "MedGuard backend is running",
    }


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "database": "connected",
    }


# --------------------------------------------------
# PATIENT MANAGEMENT
# --------------------------------------------------

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
            "allergies": [
                item for item in row["allergies"].split("|") if item
            ],
            "conditions": [
                item for item in row["conditions"].split("|") if item
            ],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.post("/api/patients")
def create_patient(patient: PatientInput):
    created_at = datetime.now().isoformat(timespec="seconds")

    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO patients
                (name, age, allergies, conditions, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient.name.strip(),
                patient.age,
                "|".join(patient.allergies),
                "|".join(patient.conditions),
                created_at,
            ),
        )

        patient_id = cursor.lastrowid

    return {
        "success": True,
        "message": "Patient profile saved",
        "id": patient_id,
    }


# --------------------------------------------------
# PRESCRIPTION TEXT EXTRACTION
# Basic keyword matching only. Not OCR or AI diagnosis.
# --------------------------------------------------

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
        "medications": found,
        "notice": (
            "Keyword-based demo extraction. Verify every medicine "
            "against the original prescription with a qualified professional."
        ),
    }


# --------------------------------------------------
# MEDICATION RISK SCREENING
# These rules are illustrative demonstrations only.
# They are not clinically validated.
# --------------------------------------------------

@app.post("/api/analyze")
def analyze_medications(data: AnalysisInput):
    medications = data.medications
    patient = data.patient

    names = [medicine.name.strip() for medicine in medications]
    normalized_names = [name.lower() for name in names]

    risks = []

    def add_risk(severity, title, reason, related_medicines):
        risks.append({
            "severity": severity,
            "title": title,
            "reason": reason,
            "medications": related_medicines,
        })

    # 1. Duplicate medicine names
    seen = set()

    for name in normalized_names:
        if name in seen:
            display_name = names[normalized_names.index(name)]

            add_risk(
                "HIGH",
                "Possible duplicate medication",
                (
                    f"{display_name} appears more than once in the "
                    "submitted medication list. Confirm whether this "
                    "is intentional before taking any action."
                ),
                [display_name],
            )
            seen.remove(name)

        else:
            seen.add(name)

    # 2. Illustrative interaction warning
    if "warfarin" in normalized_names and (
        "ibuprofen" in normalized_names
        or "naproxen" in normalized_names
        or "aspirin" in normalized_names
    ):
        related = [
            name for name in names
            if name.lower() in {
                "warfarin", "ibuprofen", "naproxen", "aspirin"
            }
        ]

        add_risk(
            "HIGH",
            "Potential bleeding interaction",
            (
                "Warfarin combined with certain pain relievers, including "
                "NSAIDs and aspirin, can increase bleeding risk. This "
                "prototype warning requires review by a doctor or pharmacist."
            ),
            related,
        )

    # 3. Illustrative kidney-condition warning
    kidney_condition = any(
        "kidney" in condition.lower()
        for condition in patient.conditions
    )

    if kidney_condition and (
        "ibuprofen" in normalized_names
        or "naproxen" in normalized_names
    ):
        related = [
            name for name in names
            if name.lower() in {"ibuprofen", "naproxen"}
        ]

        add_risk(
            "HIGH",
            "Medication review recommended for kidney disease",
            (
                "Some anti-inflammatory medicines may worsen kidney "
                "function in susceptible patients. A qualified professional "
                "should review the medication and patient history."
            ),
            related,
        )

    # 4. Illustrative allergy-name matching
    for allergy in patient.allergies:
        allergy_lower = allergy.lower().strip()

        if not allergy_lower:
            continue

        for name in names:
            name_lower = name.lower()

            matches = (
                allergy_lower == name_lower
                or (
                    allergy_lower in {"penicillin", "penicillins"}
                    and name_lower == "amoxicillin"
                )
            )

            if matches:
                add_risk(
                    "HIGH",
                    "Possible medication-allergy conflict",
                    (
                        f"The patient's recorded allergy '{allergy}' may "
                        f"be relevant to '{name}'. Do not rely on this "
                        "prototype to determine whether administration is safe; "
                        "obtain prompt professional review."
                    ),
                    [name],
                )

    # 5. Illustrative polypharmacy flag
    if len(medications) >= 5:
        add_risk(
            "MEDIUM",
            "Multiple medications require review",
            (
                f"{len(medications)} medication entries were submitted. "
                "A medication review may help identify interactions, "
                "duplicates, or medicines that need closer monitoring."
            ),
            names,
        )

    # 6. Older-patient review reminder
    if patient.age >= 65 and len(medications) >= 4:
        add_risk(
            "MEDIUM",
            "Additional medication review may be appropriate",
            (
                "Age and the number of medication entries can be reasons "
                "to review the full medication list, medical history, "
                "and doses with a qualified professional."
            ),
            names,
        )

    report = {
        "patient_name": patient.name,
        "patient_age": patient.age,
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "medication_count": len(medications),
        "medications": [
            {
                "name": medicine.name,
                "dose": medicine.dose,
                "frequency": medicine.frequency,
            }
            for medicine in medications
        ],
        "risk_count": len(risks),
        "risks": risks,
        "notice": (
            "Hackathon prototype only. Its rules are limited and not "
            "clinically validated. No warnings does not mean that a "
            "medication combination is safe. Confirm prescriptions with "
            "a qualified doctor or pharmacist."
        ),
    }

    # Save report to database
    import json

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO reports
                (patient_name, medication_count, risk_count,
                 report_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                patient.name,
                len(medications),
                len(risks),
                json.dumps(report),
                report["analyzed_at"],
            ),
        )

    return report


# --------------------------------------------------
# REPORT HISTORY
# --------------------------------------------------

@app.get("/api/reports")
def get_reports():
    import json

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, patient_name, medication_count,
                   risk_count, report_json, created_at
            FROM reports
            ORDER BY id DESC
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "patient_name": row["patient_name"],
            "medication_count": row["medication_count"],
            "risk_count": row["risk_count"],
            "created_at": row["created_at"],
            "report": json.loads(row["report_json"]),
        }
        for row in rows
    ]