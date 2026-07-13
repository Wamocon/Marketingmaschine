from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .schemas import EvidenceItem


class EvidenceVault:
    def __init__(self, items: Iterable[EvidenceItem] = (), *, version: str = "") -> None:
        self._items = {item.id: item for item in items}
        self.version = str(version).strip()

    @classmethod
    def from_json_file(cls, path: str | Path) -> "EvidenceVault":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        items = [
            EvidenceItem(
                id=item["id"],
                claim=item["claim"],
                source_type=item["source_type"],
                source_ref=item["source_ref"],
                approved_for_public_use=bool(item.get("approved_for_public_use", False)),
                consent_ref=item.get("consent_ref", ""),
                owner=item.get("owner", ""),
                created_at=item.get("created_at", ""),
            )
            for item in data.get("items", [])
        ]
        return cls(items, version=str(data.get("version", "")).strip())

    def validate_proof_sources(self, proof_sources: list[str]) -> list[str]:
        errors: list[str] = []
        for source in proof_sources:
            item = self._items.get(source)
            if item is None:
                errors.append(f"proof source is not in approved evidence vault: {source}")
                continue
            if not item.approved_for_public_use:
                errors.append(f"proof source is not approved for public use: {source}")
            if item.source_type in {"customer_story", "employee_story", "applicant_story"} and not item.consent_ref:
                errors.append(f"proof source requires consent reference: {source}")
        return errors

    def records_for(self, proof_sources: list[str]) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for source in proof_sources:
            item = self._items.get(source)
            if item is None:
                continue
            records.append(
                {
                    "id": item.id,
                    "claim": item.claim,
                    "source_type": item.source_type,
                    "source_ref": item.source_ref,
                    "approved_for_public_use": item.approved_for_public_use,
                    "consent_ref": item.consent_ref,
                    "owner": item.owner,
                    "created_at": item.created_at,
                    "vault_version": self.version,
                }
            )
        return records
