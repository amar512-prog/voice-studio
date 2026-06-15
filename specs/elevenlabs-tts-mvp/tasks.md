# Implementation Plan

## Phase 1: Foundation

- [ ] 1. Create project structure and core configuration
  - [ ] 1.1 Add FastAPI app scaffold.
  - [ ] 1.2 Add environment loading for `ELEVENLABS_API_KEY`.
  - [ ] 1.3 Add local `data/` directories and path helpers.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 9.1, 10.1_

- [ ] 2. Implement StorageService
  - [ ] 2.1 Store generated MP3 and `.m4a` files.
  - [ ] 2.2 Store voice source, normalized, consent, preview, and registry files.
  - [ ] 2.3 Store audit events for clone and generation actions.
  - _Requirements: 2.3, 9.1, 9.2_

- [ ] 3. Implement VoiceRegistry
  - [ ] 3.1 Create voice record model and persistence.
  - [ ] 3.2 Filter usable voices by approval state.
  - [ ] 3.3 Verify remote ElevenLabs voice availability and mark unavailable records.
  - _Requirements: 1.1, 1.2, 1.3, 3.1, 8.4_

## Phase 2: Voice Creation

- [ ] 4. Implement VoiceCloneService and VoiceCloneUI
  - [ ] 4.1 Add upload path for clone audio.
  - [ ] 4.2 Add browser-recording submission path.
  - [ ] 4.3 Validate consent metadata and audio basics before provider calls.
  - [ ] 4.4 Call ElevenLabs IVC and persist the returned voice ID.
  - _Requirements: 2.1, 2.2, 2.3_

## Phase 3: Generation Core

- [ ] 5. Implement speech context presets
  - [ ] 5.1 Add preset enum and validation.
  - [ ] 5.2 Map presets to model IDs, voice settings, and review requirements.
  - [ ] 5.3 Require review for high-risk presets.
  - _Requirements: 4.1, 4.2, 4.3_

- [ ] 6. Implement DurationService
  - [ ] 6.1 Estimate duration from text and WPM.
  - [ ] 6.2 Return yellow warning for estimated over-target duration.
  - [ ] 6.3 Measure generated MP3 duration.
  - [ ] 6.4 Return red warning for actual over-limit duration and clear warning when safe.
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 7. Implement TtsGenerationService
  - [ ] 7.1 Resolve approved voice and settings.
  - [ ] 7.2 Call ElevenLabs TTS with selected voice/model/output format.
  - [ ] 7.3 Save MP3 output through StorageService.
  - _Requirements: 3.1, 3.2_

- [ ] 8. Implement AudioExportService
  - [ ] 8.1 Skip export for `mp3_only`.
  - [ ] 8.2 Convert MP3 to AAC mono `.m4a` for `linkedin_m4a`.
  - [ ] 8.3 Preserve MP3 and mark `m4a_export_failed` when export fails.
  - _Requirements: 6.1, 6.2, 6.3_

## Phase 4: API and UI

- [ ] 9. Implement ApiService endpoints
  - [ ] 9.1 Implement `GET /api/voices`.
  - [ ] 9.2 Implement `POST /api/tts`.
  - [ ] 9.3 Implement `POST /api/tts/batch`.
  - [ ] 9.4 Implement `GET /api/jobs/{job_id}`.
  - [ ] 9.5 Reject target durations above 60 seconds and unsupported sending requests.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 10.1, 10.2, 10.4_

- [ ] 10. Implement SingleGenerationUI
  - [ ] 10.1 Add text, voice, accent, speech context, duration, WPM, and export inputs.
  - [ ] 10.2 Show yellow pre-generation warning without blocking.
  - [ ] 10.3 Show red post-generation warning and clear yellow state.
  - [ ] 10.4 Show MP3 and optional `.m4a` downloads.
  - _Requirements: 3.3, 5.2, 5.3, 5.4_

## Phase 5: Bulk Jobs

- [ ] 11. Implement BulkWorkbookService
  - [ ] 11.1 Require `tts_requests` worksheet.
  - [ ] 11.2 Validate required headers.
  - [ ] 11.3 Write result workbook with status, warnings, URLs, and errors.
  - _Requirements: 7.1, 7.2, 7.4_

- [ ] 12. Implement JobQueue
  - [ ] 12.1 Create stable idempotency keys for rows.
  - [ ] 12.2 Run queued jobs through generation, duration measurement, export, and storage.
  - [ ] 12.3 Retry safe transient provider failures and persist final errors.
  - _Requirements: 7.3, 8.3, 10.3_

- [ ] 13. Implement BulkGenerationUI
  - [ ] 13.1 Upload `.xlsx` workbooks.
  - [ ] 13.2 Show batch status.
  - [ ] 13.3 Download completed result workbook.
  - _Requirements: 7.1, 7.4, 8.2, 8.3_

## Phase 6: Review and Safety

- [ ] 14. Implement ReviewService
  - [ ] 14.1 Record reviewer, status, timestamp, and notes.
  - [ ] 14.2 Require review for high-risk presets and over-limit generated audio.
  - _Requirements: 4.3, 9.3_

- [ ] 15. Add safety and regression tests
  - [ ] 15.1 Test missing and unknown field errors.
  - [ ] 15.2 Test target duration rejection above 60 seconds.
  - [ ] 15.3 Test approved voice filtering.
  - [ ] 15.4 Test Excel validation.
  - [ ] 15.5 Test MP3 preservation when `.m4a` export fails.
  - _Requirements: 1.2, 6.3, 7.1, 7.2, 10.1, 10.2_
