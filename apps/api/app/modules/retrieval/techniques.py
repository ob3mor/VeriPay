"""Search techniques: exact identifiers, normalized text, full-text, trigrams.

Two backends behind ONE interface (Prompt-03 §2), selected purely by dialect:

- ``PortableBackend`` (SQLite / dev-test fallback): normalized substring +
  token overlap + Python trigram similarity (Dice over char 3-grams, the same
  0..1 scale as pg_trgm). Candidates come from the org-scoped projection.
- ``PostgresBackend`` (canonical): PostgreSQL full-text (``to_tsvector`` @@
  ``plainto_tsquery`` with the ``simple`` config — deterministic across
  scripts, no stemming) and ``pg_trgm`` trigram similarity, written as
  SQLAlchemy expressions over the source tables. Every UNION arm repeats the
  org predicate — org filtering happens before candidate generation.

pgvector is OPTIONAL (Prompt-03 §2): guarded behind
``settings.retrieval_pgvector_enabled`` + a PostgreSQL dialect + an existing
``vector`` extension (migration 0002 creates both only when the flag is set).
Unavailable anywhere → the technique is skipped with an explicit note; search
never fails because of it.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

from sqlalchemy import Text, literal, select, text as sql_text, union_all
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ExtractionField,
    Invoice,
    PurchaseOrder,
    ReviewAction,
    Vendor,
    VendorBankAccount,
)

from app.modules.retrieval.indexing import (
    ENTITY_EXTRACTION_FIELD,
    ENTITY_INVOICE,
    ENTITY_PURCHASE_ORDER,
    ENTITY_REVIEW_ACTION,
    ENTITY_VENDOR,
    ENTITY_VENDOR_BANK_ACCOUNT,
    ALL_ENTITY_TYPES,
    SearchIndex,
)
from app.modules.retrieval.normalize import (
    expand_label_variants,
    normalize_identifier,
    normalize_text,
    trigram_similarity,
)
from app.modules.vendors.service import fingerprint_account

# Canonical technique names — fusion weights are keyed by these.
TECH_EXACT = "exact"
TECH_TEXT = "text"
TECH_TRIGRAM = "trigram"
TECH_VECTOR = "vector"
TECH_GRAPH = "graph"  # deterministic evidence-graph edges (score 1.0)

Ref = tuple[str, str]


@dataclass
class RankedHit:
    """One candidate hit from one technique, with its citable explanation."""

    ref: Ref
    score: float  # 0..1 within the technique (order is what RRF consumes)
    explanation: str
    matched_field: str | None = None


@dataclass
class TechniqueResult:
    """One technique's ranked candidate list for one query."""

    technique: str
    backend: str
    hits: list[RankedHit] = field(default_factory=list)
    note: str | None = None


class SearchBackend:
    """Dialect-selected strategy; both implementations share ``run``."""

    name: str = "abstract"

    def run(
        self,
        db: Session,
        *,
        org_id: object,
        query: str,
        index: SearchIndex,
        entity_types=None,
        limit_per_technique: int = 100,
    ) -> list[TechniqueResult]:
        raise NotImplementedError


def get_backend(db: Session) -> SearchBackend:
    """Selected by dialect only — the interface is identical (Prompt-03 §2)."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return PostgresBackend()
    return PortableBackend()


# ===========================================================================
# Portable backend (SQLite dev/test fallback — normalized substring +
# difflib/trigram similarity)
# ===========================================================================
class PortableBackend(SearchBackend):
    name = "portable"

    def run(
        self,
        db: Session,
        *,
        org_id: object,
        query: str,
        index: SearchIndex,
        entity_types=None,
        limit_per_technique: int = 100,
    ) -> list[TechniqueResult]:
        del db  # the portable path needs no extra SQL; index is prebuilt
        filtered = (
            index if entity_types is None else index.filter_types(entity_types)
        )
        return [
            self._exact(query, filtered, limit_per_technique),
            self._normalized_text(query, filtered, limit_per_technique),
            self._trigram(query, filtered, limit_per_technique),
        ]

    # ------------------------------------------------------------- exact ---
    def _exact(self, query: str, index: SearchIndex, limit: int) -> TechniqueResult:
        norm_id = normalize_identifier(query)
        norm_text = normalize_text(query)
        digits = "".join(ch for ch in norm_id if ch.isdigit())
        hits: list[RankedHit] = []
        for row in index.rows:
            for field_name, value in row.identifier_fields.items():
                matched: str | None = None
                if value and value == norm_id:
                    matched = f"identifier {field_name} = {value!r}"
                elif value and value == norm_text:
                    matched = f"identifier {field_name} = {value!r} (normalized text)"
                elif (
                    field_name == "account_fingerprint"
                    and len(digits) >= 4
                    and value == fingerprint_account(digits)
                ):
                    matched = "account fingerprint of the digits in the query"
                elif (
                    field_name == "account_number_last4"
                    and len(digits) >= 4
                    and value == digits[-4:]
                ):
                    matched = f"account last4 = {value!r}"
                if matched:
                    hits.append(
                        RankedHit(
                            ref=row.ref,
                            score=1.0,
                            explanation=f"Exact match: {matched}",
                            matched_field=field_name,
                        )
                    )
                    break
        hits.sort(key=lambda h: h.ref)
        return TechniqueResult(TECH_EXACT, self.name, hits[:limit])

    # ---------------------------------------------------- normalized text ---
    def _normalized_text(
        self, query: str, index: SearchIndex, limit: int
    ) -> TechniqueResult:
        """Normalized token matching with AR/EN label expansion — the
        diacritics-insensitive, digit-insensitive fallback path.

        Score hierarchy (deterministic): identifier equality 1.0 > legal-form
        name equality 0.98 > phrase containment 0.95 > token overlap.
        """
        q_norm = normalize_text(query)
        if not q_norm:
            return TechniqueResult(TECH_TEXT, self.name, [], note="empty query")
        norm_id = normalize_identifier(query)
        q_tokens = expand_label_variants(q_norm.split())
        q_token_set = set(q_tokens)
        q_phrase = " ".join(q_tokens)
        hits: list[RankedHit] = []
        for row in index.rows:
            row_tokens = set(row.tokens)
            if row.name_key():
                row_tokens |= set(row.name_key().split())
            identifier_hit = any(
                value and value == norm_id
                for value in row.identifier_fields.values()
            )
            name_equal = bool(row.name_key()) and q_phrase == row.name_key()
            containment = q_phrase in row.normalized or q_norm in row.normalized
            overlap = len(q_token_set & row_tokens)
            if identifier_hit:
                score = 1.0
            elif name_equal:
                score = 0.98
            elif containment:
                score = 0.95
            elif overlap == 0:
                continue
            else:
                score = round(0.9 * overlap / len(q_token_set), 6)
            hits.append(
                RankedHit(
                    ref=row.ref,
                    score=score,
                    explanation=(
                        "Normalized text match"
                        + (
                            " (identifier equality)"
                            if identifier_hit
                            else (
                                " (legal-form name equality)"
                                if name_equal
                                else (
                                    " (phrase contained)"
                                    if containment
                                    else f" ({overlap}/{len(q_token_set)} query tokens)"
                                )
                            )
                        )
                    ),
                    matched_field="text",
                )
            )
        hits.sort(key=lambda h: (-h.score, h.ref))
        return TechniqueResult(TECH_TEXT, self.name, hits[:limit])

    # ------------------------------------------------------------ trigram ---
    def _trigram(self, query: str, index: SearchIndex, limit: int) -> TechniqueResult:
        """OCR-error tolerance: Dice similarity over character trigrams
        (the portable twin of pg_trgm's ``similarity()``). Identifier equality
        subsumes trigram similarity (identical strings score 1.0)."""
        settings = get_settings()
        threshold = settings.retrieval_trigram_threshold
        q_norm = normalize_text(query)
        norm_id = normalize_identifier(query)
        if not q_norm:
            return TechniqueResult(TECH_TRIGRAM, self.name, [], note="empty query")
        hits: list[RankedHit] = []
        for row in index.rows:
            identifier_hit = any(
                value and value == norm_id
                for value in row.identifier_fields.values()
            )
            best = trigram_similarity(q_norm, row.normalized)
            if row.name_key():
                best = max(best, trigram_similarity(q_norm, row.name_key()))
            for value in row.identifier_fields.values():
                if value:
                    best = max(best, trigram_similarity(q_norm, value))
            if identifier_hit:
                best = 1.0
            if best >= threshold:
                hits.append(
                    RankedHit(
                        ref=row.ref,
                        score=round(best, 6),
                        explanation=f"Trigram similarity {best:.3f} ≥ {threshold}",
                        matched_field="text",
                    )
                )
        hits.sort(key=lambda h: (-h.score, h.ref))
        return TechniqueResult(TECH_TRIGRAM, self.name, hits[:limit])


# ===========================================================================
# PostgreSQL backend — to_tsvector + pg_trgm as SQLAlchemy expressions
# ===========================================================================
# (entity type → model, searchable columns, identifier columns)
_PG_SOURCES: dict[str, dict] = {
    ENTITY_VENDOR: {
        "model": Vendor,
        "text_columns": [Vendor.display_name, Vendor.legal_name],
    },
    ENTITY_VENDOR_BANK_ACCOUNT: {
        "model": VendorBankAccount,
        "text_columns": [VendorBankAccount.account_holder_name, VendorBankAccount.bank_name],
    },
    ENTITY_INVOICE: {
        "model": Invoice,
        "text_columns": [
            Invoice.invoice_number,
            Invoice.remittance_bank_name_raw,
            Invoice.remittance_account_raw,
        ],
    },
    ENTITY_PURCHASE_ORDER: {
        "model": PurchaseOrder,
        "text_columns": [PurchaseOrder.po_number, PurchaseOrder.description],
    },
    ENTITY_EXTRACTION_FIELD: {
        "model": ExtractionField,
        "text_columns": [ExtractionField.field_name, ExtractionField.field_value],
    },
    ENTITY_REVIEW_ACTION: {
        "model": ReviewAction,
        "text_columns": [ReviewAction.action_type, ReviewAction.body],
    },
}


class PostgresBackend(SearchBackend):
    name = "postgres"

    def run(
        self,
        db: Session,
        *,
        org_id: object,
        query: str,
        index: SearchIndex,
        entity_types=None,
        limit_per_technique: int = 100,
    ) -> list[TechniqueResult]:
        del index  # the SQL path scores inside the database
        wanted = [t for t in (entity_types or ALL_ENTITY_TYPES) if t in _PG_SOURCES]
        return [
            self._exact(db, org_id, query, wanted, limit_per_technique),
            self._full_text(db, org_id, query, wanted, limit_per_technique),
            self._trigram(db, org_id, query, wanted, limit_per_technique),
            self._vector(db, org_id, query, limit_per_technique),
        ]

    # ------------------------------------------------------------- exact ---
    def _exact(self, db, org_id, query, wanted, limit) -> TechniqueResult:
        from sqlalchemy import func

        norm = normalize_identifier(query)
        digits = "".join(ch for ch in norm if ch.isdigit())
        branches = []
        if ENTITY_INVOICE in wanted and norm:
            inv = func.regexp_replace(
                func.upper(func.cast(Invoice.invoice_number, Text)),
                "[^A-Z0-9]",
                "",
                "g",
            )
            branches.append(
                select(
                    literal(ENTITY_INVOICE).label("entity_type"),
                    Invoice.id.label("entity_id"),
                    literal(1.0).label("score"),
                    literal("invoice_number").label("matched_field"),
                ).where(
                    Invoice.organization_id == org_id,
                    inv == norm,
                )
            )
        if ENTITY_PURCHASE_ORDER in wanted and norm:
            po = func.regexp_replace(
                func.upper(func.cast(PurchaseOrder.po_number, Text)),
                "[^A-Z0-9]",
                "",
                "g",
            )
            branches.append(
                select(
                    literal(ENTITY_PURCHASE_ORDER).label("entity_type"),
                    PurchaseOrder.id.label("entity_id"),
                    literal(1.0).label("score"),
                    literal("po_number").label("matched_field"),
                ).where(
                    PurchaseOrder.organization_id == org_id,
                    po == norm,
                )
            )
        if ENTITY_VENDOR in wanted and query:
            v = Vendor
            tax_norm = func.regexp_replace(
                func.upper(func.cast(v.tax_id, Text)), "[^A-Z0-9]", "", "g"
            )
            branches.append(
                select(
                    literal(ENTITY_VENDOR).label("entity_type"),
                    v.id.label("entity_id"),
                    literal(1.0).label("score"),
                    literal("tax_id").label("matched_field"),
                ).where(
                    v.organization_id == org_id,
                    v.tax_id.is_not(None),
                    tax_norm == norm,
                )
            )
        if ENTITY_VENDOR_BANK_ACCOUNT in wanted and len(digits) >= 4:
            vba = VendorBankAccount
            branches.append(
                select(
                    literal(ENTITY_VENDOR_BANK_ACCOUNT).label("entity_type"),
                    vba.id.label("entity_id"),
                    literal(1.0).label("score"),
                    literal("account_fingerprint/last4").label("matched_field"),
                ).where(
                    vba.organization_id == org_id,
                    vba.status == "approved",
                    (vba.account_fingerprint == fingerprint_account(digits))
                    | (vba.account_number_last4 == digits[-4:]),
                )
            )
        return self._union(db, branches, TECH_EXACT, limit)

    # ---------------------------------------------------------- full text ---
    def _full_text(self, db, org_id, query, wanted, limit) -> TechniqueResult:
        from sqlalchemy import func

        # OR semantics (' | '-joined tokens): recall-oriented so a query with
        # an unmatched word (e.g. a legal-form variant like "company" vs
        # "co.") still reaches candidates; ts_rank provides the ordering.
        # Tokens are sanitized to word characters before to_tsquery (it is a
        # parser input, not a safe literal).
        token_sql = re.sub(r"[^0-9A-Za-z\u0600-\u06FF]+", "", normalize_text(query))
        tokens = [t for t in token_sql.split() if t]
        if not tokens:
            return TechniqueResult(TECH_TEXT, self.name, [], note="empty query")
        tsquery = func.to_tsquery("simple", " | ".join(tokens))
        branches = []
        for entity_type, source in _PG_SOURCES.items():
            if entity_type not in wanted:
                continue
            model = source["model"]
            tsvector = func.to_tsvector(
                "simple", func.concat_ws(" ", *source["text_columns"])
            )
            branches.append(
                select(
                    literal(entity_type).label("entity_type"),
                    model.id.label("entity_id"),
                    func.ts_rank(tsvector, tsquery).label("score"),
                    literal("textsearch").label("matched_field"),
                ).where(
                    # Org predicate inside every UNION arm — candidate
                    # generation is tenant-scoped at the SQL level.
                    model.organization_id == org_id,
                    tsvector.op("@@")(tsquery),
                )
            )
        return self._union(db, branches, TECH_TEXT, limit, order_desc=True)

    # ------------------------------------------------------------ trigram ---
    def _trigram(self, db, org_id, query, wanted, limit) -> TechniqueResult:
        from sqlalchemy import func

        if not _extension_available(db, "pg_trgm"):
            return TechniqueResult(
                TECH_TRIGRAM,
                self.name,
                [],
                note="pg_trgm extension unavailable — trigram technique skipped",
            )
        threshold = get_settings().retrieval_trigram_threshold
        q_norm = normalize_text(query)
        if not q_norm:
            return TechniqueResult(TECH_TRIGRAM, self.name, [], note="empty query")
        branches = []
        for entity_type, source in _PG_SOURCES.items():
            if entity_type not in wanted:
                continue
            model = source["model"]
            haystack = func.lower(func.concat_ws(" ", *source["text_columns"]))
            sim = func.similarity(haystack, q_norm)
            branches.append(
                select(
                    literal(entity_type).label("entity_type"),
                    model.id.label("entity_id"),
                    sim.label("score"),
                    literal("trigram").label("matched_field"),
                ).where(
                    model.organization_id == org_id,
                    sim >= threshold,
                )
            )
        return self._union(db, branches, TECH_TRIGRAM, limit, order_desc=True)

    # ------------------------------------------------------------- vector ---
    def _vector(self, db, org_id, query, limit) -> TechniqueResult:
        """OPTIONAL pgvector path — skipped unless flag + dialect + extension
        all hold. Embeddings live in the companion table created by migration
        0002 (only when enabled); absence is a clean, explicit skip."""
        if not vector_search_available(db):
            return TechniqueResult(
                TECH_VECTOR,
                self.name,
                [],
                note="pgvector disabled or unavailable — vector technique skipped",
            )
        dim = get_settings().retrieval_embedding_dim
        qvec = embed_text(query, dim)
        vec_literal = "[" + ",".join(f"{v:.6f}" for v in qvec) + "]"
        rows = db.execute(
            sql_text(
                "SELECT entity_type, entity_id, 1 - (embedding <=> :vec) AS score"
                " FROM retrieval_embeddings"
                " WHERE organization_id = :org_id"
                " ORDER BY embedding <=> :vec LIMIT :limit"
            ),
            {"vec": vec_literal, "org_id": str(org_id), "limit": limit},
        ).all()
        hits = [
            RankedHit(
                ref=(str(r.entity_type), str(r.entity_id)),
                score=float(r.score),
                explanation="pgvector cosine similarity (optional path)",
                matched_field="embedding",
            )
            for r in rows
        ]
        hits.sort(key=lambda h: (-h.score, h.ref))
        return TechniqueResult(TECH_VECTOR, self.name, hits)

    # ------------------------------------------------------------- shared ---
    def _union(self, db, branches, technique, limit, *, order_desc=False):
        if not branches:
            return TechniqueResult(technique, self.name, [])
        union_sq = union_all(*branches).subquery()
        outer = select(
            union_sq.c.entity_type,
            union_sq.c.entity_id,
            union_sq.c.score,
            union_sq.c.matched_field,
        )
        if order_desc:
            outer = outer.order_by(union_sq.c.score.desc())
        rows = db.execute(outer.limit(limit)).all()
        hits = [
            RankedHit(
                ref=(str(r.entity_type), str(r.entity_id)),
                score=float(r.score),
                explanation=(
                    f"{technique} match on {r.matched_field} (score {float(r.score):.4f})"
                ),
                matched_field=str(r.matched_field),
            )
            for r in rows
        ]
        if not order_desc:
            hits.sort(key=lambda h: (-h.score, h.ref))
        return TechniqueResult(technique, self.name, hits)


def _extension_available(db: Session, extname: str) -> bool:
    try:
        row = db.execute(
            sql_text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = :e)"),
            {"e": extname},
        ).scalar()
        return bool(row)
    except Exception:
        # Any failure (non-PG driver, permissions) = extension unavailable.
        return False


# ===========================================================================
# OPTIONAL pgvector plumbing
# ===========================================================================
def vector_search_available(db: Session) -> bool:
    """True only when the flag is set AND we are on PostgreSQL AND the vector
    extension exists. Default deployments: False — never required."""
    settings = get_settings()
    if not settings.retrieval_pgvector_enabled:
        return False
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return False
    return _extension_available(db, "vector")


def embed_text(text_value: str, dim: int) -> list[float]:
    """Deterministic dependency-free feature-hashing embedder.

    Honest placeholder quality: tokens hash into ``dim`` buckets with
    signed weights; the seam exists so a real multilingual embedder can drop
    in without interface changes. Determinism (not linguistic quality) is the
    property the hybrid pipeline needs for the optional path.
    """
    vec = [0.0] * dim
    for token in normalize_text(text_value).split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") % dim
        sign = 1.0 if digest[8] % 2 == 0 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
