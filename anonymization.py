"""Anonymisation des métadonnées DICOM.

Par défaut, aucun identifiant nominatif n'est conservé. On ne modifie JAMAIS
les fichiers source ; l'anonymisation ne s'applique qu'aux valeurs recopiées
dans ``metadata.json`` et les exports.
"""

from __future__ import annotations

from typing import Any

# Champs directement nominatifs, toujours retirés en mode anonyme.
DIRECT_IDENTIFIERS: frozenset[str] = frozenset({
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "OtherPatientIDs",
    "OtherPatientNames",
    "AccessionNumber",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "RequestingPhysician",
})

# Champs retirés uniquement en mode strict (établissement, dates étendues).
STRICT_IDENTIFIERS: frozenset[str] = frozenset({
    "InstitutionName",
    "InstitutionAddress",
    "InstitutionalDepartmentName",
    "StationName",
    "DeviceSerialNumber",
    "StudyDate",
    "SeriesDate",
    "AcquisitionDate",
    "ContentDate",
})


def is_blocked(field: str, anonymize: bool, strict: bool = False) -> bool:
    """Indique si un champ doit être exclu des métadonnées exportées."""
    if not anonymize:
        return False
    if field in DIRECT_IDENTIFIERS:
        return True
    if strict and field in STRICT_IDENTIFIERS:
        return True
    return False


def safe_value(field: str, value: Any, anonymize: bool, strict: bool = False) -> Any:
    """Retourne la valeur du champ, ou ``None`` si elle doit être masquée."""
    if is_blocked(field, anonymize, strict):
        return None
    return value


def anonymization_warning() -> str:
    return (
        "AVERTISSEMENT : --keep-identifiers est actif. Les identifiants patient "
        "(nom, ID, date de naissance, numéro d'accession, médecin référent...) "
        "seront conservés dans les métadonnées et le ZIP. Ne partagez pas ces "
        "fichiers en dehors d'un cadre autorisé."
    )
