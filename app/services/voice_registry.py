from __future__ import annotations

from datetime import datetime

from app.models import VoiceCreateRequest, VoiceRecord
from app.services.storage import StorageService, new_id, now_utc
from app.services.voice_filter import is_registry_eligible


class VoiceRegistry:
    def __init__(self, storage: StorageService) -> None:
        self.storage = storage

    def list(self) -> list[VoiceRecord]:
        raw_records = self.storage.read_json(self.storage.registry_path, [])
        return [
            VoiceRecord.model_validate(record)
            for record in raw_records
            if is_registry_eligible(record)
        ]

    def save_all(self, records: list[VoiceRecord]) -> None:
        self.storage.write_json(
            self.storage.registry_path,
            [record.model_dump(mode="json") for record in records],
        )

    def upsert(self, request: VoiceCreateRequest, provider_metadata: dict | None = None) -> VoiceRecord:
        records = self.list()
        existing = next((record for record in records if record.voice_id == request.voice_id), None)
        timestamp = now_utc()
        if existing:
            existing.display_name = request.display_name
            existing.source_type = request.source_type
            existing.accent = request.accent
            existing.consent_status = request.consent_status
            existing.updated_at = timestamp
            existing.provider_metadata = provider_metadata or existing.provider_metadata
            self.save_all(records)
            return existing

        record = VoiceRecord(
            id=new_id("voice"),
            display_name=request.display_name,
            voice_id=request.voice_id,
            source_type=request.source_type,
            accent=request.accent,
            consent_status=request.consent_status,
            provider_metadata=provider_metadata or {},
            created_at=timestamp,
            updated_at=timestamp,
        )
        records.append(record)
        self.save_all(records)
        return record

    def upsert_record(self, record: VoiceRecord) -> VoiceRecord:
        records = self.list()
        now = datetime.now(record.updated_at.tzinfo)
        record.updated_at = now
        for index, existing in enumerate(records):
            if existing.voice_id == record.voice_id or existing.id == record.id:
                records[index] = record
                self.save_all(records)
                return record
        records.append(record)
        self.save_all(records)
        return record

    def delete(self, record_id: str) -> VoiceRecord | None:
        records = self.list()
        removed = next((record for record in records if record.id == record_id), None)
        if removed is None:
            return None
        self.save_all([record for record in records if record.id != record_id])
        return removed

    def find_by_provider_voice_id(self, voice_id: str) -> VoiceRecord | None:
        return next((record for record in self.list() if record.voice_id == voice_id), None)
