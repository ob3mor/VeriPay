# ADR 0003 — Provider-agnostic storage/OCR adapters

Status: Accepted · 2026-10-17

## Context

Document storage is the local filesystem by default and MinIO/S3 under PROFILE A; a cloud object store (Azure Blob) is likely for PROFILE B. The OCR engine is undecided — a stub now, with Tesseract (local) and Azure Document Intelligence (cloud) as candidates. Modules must not know vendor SDKs or vendor behavior, and tests must run without network services.

## Decision

Two `typing.Protocol` seams (structural, no inheritance coupling), selected by settings, with modules depending on **protocols only** (ARCHITECTURE §5 rule D3):

- **`StorageProvider`** — designed now, implemented in Phase 1: `LocalFilesystemProvider` (default) and `MinIOS3Provider`; `AzureBlobStorageProvider` later. Object keys are tenant-prefixed `{org_id}/{document_id}/{sha256}{ext}`.
- **`OcrProvider`** — Phase 2 **interface stub**: protocol + `StubOcrProvider` only (synthetic output, `confidence = None`, always below the confidence gate). Real engines are Phase 2+ additions that touch no module code.

Every implementation must pass the same shared contract test suite (roundtrip, not-found, delete idempotency, content-type preservation; for OCR: span/confidence schema shape).

## Consequences

**Positive:** swapping or adding a vendor never changes module code; tests use local/in-memory fakes with no network; vendor lock-in is contained inside one adapter directory.

**Negative:** one layer of indirection plus contract-test upkeep; provider-specific capabilities (presigned URLs, server-side page limits, native confidence scores) must be modeled as optional protocol members — they must not leak vendor types into modules or schemas.
