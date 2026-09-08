"""Base classes for campaign source synchronization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationError:
    message: str
    invalid_rows: list[int] | None = None


@dataclass
class ValidationResult:
    is_valid: bool
    error: ValidationError | None = None
    headers: list[str] | None = field(default=None, repr=False)
    rows: list[list[str]] | None = field(default=None, repr=False)


class CampaignSourceSyncService(ABC):
    @staticmethod
    def normalize_headers(headers: list[str]) -> list[str]:
        return [h.strip().lower() for h in headers]

    @staticmethod
    def validate_source_data(
        headers: list[str], rows: list[list[str]]
    ) -> ValidationResult:
        normalized_headers = CampaignSourceSyncService.normalize_headers(headers)
        if "phone_number" not in normalized_headers:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message="Source must contain a 'phone_number' column"
                ),
            )
        phone_idx = normalized_headers.index("phone_number")
        invalid_rows: list[int] = []
        for row_idx, row in enumerate(rows, start=2):
            if len(row) <= phone_idx:
                continue
            phone = row[phone_idx].strip()
            if phone and not phone.startswith("+"):
                invalid_rows.append(row_idx)
        if invalid_rows:
            shown = invalid_rows[:5]
            suffix = (
                f" and {len(invalid_rows) - 5} more"
                if len(invalid_rows) > 5
                else ""
            )
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message=(
                        f"Invalid phone numbers in rows: {', '.join(map(str, shown))}"
                        f"{suffix}. All phone numbers must include country code (start with '+')"
                    ),
                    invalid_rows=invalid_rows,
                ),
            )
        seen: dict[str, int] = {}
        duplicate_rows: list[int] = []
        for row_idx, row in enumerate(rows, start=2):
            if len(row) <= phone_idx:
                continue
            phone = row[phone_idx].strip()
            if not phone:
                continue
            if phone in seen:
                duplicate_rows.append(row_idx)
            else:
                seen[phone] = row_idx
        if duplicate_rows:
            shown = duplicate_rows[:5]
            suffix = (
                f" and {len(duplicate_rows) - 5} more"
                if len(duplicate_rows) > 5
                else ""
            )
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message=(
                        f"Duplicate phone numbers found in rows: "
                        f"{', '.join(map(str, shown))}{suffix}"
                    ),
                    invalid_rows=duplicate_rows,
                ),
            )
        return ValidationResult(is_valid=True, headers=normalized_headers, rows=rows)

    @abstractmethod
    async def validate_source(
        self, source_id: str, organization_id: str | None = None
    ) -> ValidationResult:
        pass

    @abstractmethod
    async def sync_source_data(self, campaign_id: str) -> int:
        pass

    @staticmethod
    def build_context_variables(
        headers: list[str], row_values: list[str]
    ) -> dict[str, Any]:
        padded = row_values + [""] * max(0, len(headers) - len(row_values))
        return dict(zip(headers, padded))
