"""OcrAzureDocumentProvider — Azure Document Intelligence (optional
``[azure-ocr]`` extra), ``prebuilt-invoice`` by default.

F0 free-tier contract (owner rule: never auto-upgrade a tier):
- ``settings.azure_di_page_cap`` (default 2 — the F0 per-request page limit)
  caps how many pages of a document are analyzed. The cap is a human
  configuration decision; no code path raises it.
- The adapter NEVER switches model/service tier on its own.
- HTTP 429 is mapped to :class:`AzureDiQuotaExceededError` — an explicit
  "quota exhausted" error, NOT silently retried (retrying a spent monthly
  quota would only burn time and hide the cause).
- Transient failures (5xx, connection errors) are retried with exponential
  backoff (``azure_di_max_retries``, base 0.5s); a request timeout is
  enforced via the poller wait (``azure_di_timeout_seconds``).

The SDK is imported lazily; a caller (or test) may inject a pre-built
``client`` so the adapter is unit-testable without the cloud.

Field provenance: every Azure field becomes an OcrBlock with
``field_hint`` set (provider-side field identity), its own confidence and
bounding region — the extraction module keeps confidence as-is (None stays
None, R3) and humans verify before anything becomes fraud evidence.
"""

import time

from app.core.config import get_settings

# Azure Document Intelligence accepts these for prebuilt models.
SUPPORTED_MIMES = ("application/pdf", "image/png", "image/jpeg")

# Azure field name (prebuilt-invoice) -> VeriPay field name.
AZURE_FIELD_MAP: dict[str, str] = {
    "VendorName": "vendor_name",
    "VendorAddress": "vendor_address",
    "VendorTaxId": "vendor_tax_id",
    "CustomerName": "customer_name",
    "InvoiceId": "invoice_number",
    "InvoiceDate": "invoice_date",
    "DueDate": "due_date",
    "PurchaseOrder": "po_reference",
    "SubTotal": "subtotal",
    "TotalTax": "tax",
    "Total": "total",
    "InvoiceTotal": "total",
    "AmountDue": "total",
    "RemitToName": "bank_account_holder",
    "RemittanceAddress": "remit_address",
    "ServiceAddress": "service_address",
    "BillingAddress": "billing_address",
}

# Amount fields whose normalized value keeps the detected currency.
_AMOUNT_FIELDS = {"subtotal", "tax", "total"}


class AzureDiConfigurationError(RuntimeError):
    """The Azure DI engine is not usable here (missing SDK or credentials)."""


class AzureDiQuotaExceededError(RuntimeError):
    """HTTP 429 from the service — the F0 (or paid) quota is spent.

    Deliberately explicit: quota exhaustion requires a human decision about
    the tier; the adapter never upgrades anything and never retries 429s.
    """


class AzureDiTimeoutError(RuntimeError):
    """The analyze poller did not finish within the configured timeout."""


class _TransientError(RuntimeError):
    """Internal wrapper marking a retryable upstream failure."""


class AzureDiTransientExhaustedError(RuntimeError):
    """All retry attempts for a transient upstream failure were spent."""


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


def _classify(exc: Exception) -> str:
    """quota | transient | fatal."""
    status = _status_code(exc)
    if status == 429:
        return "quota"
    if status is not None and 500 <= status <= 599:
        return "transient"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "transient"
    return "fatal"


def _snake_case(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and (not name[i - 1].isupper() or (i + 1 < len(name) and name[i + 1].islower())):
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _polygon_to_bbox(polygon) -> tuple[float, float, float, float] | None:
    """Azure polygon: [x0,y0, x1,y1, ...] (4+ points) → (x0, y0, x1, y1)."""
    if not polygon or len(polygon) < 4:
        return None
    xs = [float(v) for v in polygon[0::2]]
    ys = [float(v) for v in polygon[1::2]]
    return (min(xs), min(ys), max(xs), max(ys))


class OcrAzureDocumentProvider:
    name = "azure"

    def __init__(
        self,
        *,
        client: object | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
        settings: object | None = None,
    ) -> None:
        s = settings or get_settings()
        self.model_id = s.azure_di_model
        self.page_cap = max(0, int(s.azure_di_page_cap))
        self.timeout_seconds = float(s.azure_di_timeout_seconds)
        self.max_retries = max(0, int(s.azure_di_max_retries))
        self.backoff_base_seconds = 0.5

        if client is not None:
            self._client = client
            return

        endpoint = endpoint or s.azure_di_endpoint
        api_key = api_key or s.azure_di_key
        if not endpoint or not api_key:
            raise AzureDiConfigurationError(
                "Azure Document Intelligence is not configured: set "
                "VERIPAY_AZURE_DI_ENDPOINT and VERIPAY_AZURE_DI_KEY."
            )
        try:
            from azure.ai.formrecognizer import DocumentAnalysisClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as exc:
            raise AzureDiConfigurationError(
                "azure-ai-formrecognizer is not installed (pip install "
                "'veripay-api[azure-ocr]')."
            ) from exc
        # retry_total=0: this adapter owns retries/backoff (policy below).
        self._client = DocumentAnalysisClient(
            endpoint, AzureKeyCredential(api_key), retry_total=0
        )

    # -- public API ---------------------------------------------------------

    def extract(self, data: bytes, mime_type: str) -> "object":  # noqa: ANN201 — OcrDocument
        from app.adapters.ocr.base import OcrBlock, OcrDocument, OcrPage

        if mime_type not in SUPPORTED_MIMES:
            raise ValueError(
                f"Azure Document Intelligence does not accept {mime_type!r}."
            )

        pages_selection = (
            [f"1-{self.page_cap}"] if self.page_cap > 0 else None
        )
        started = time.perf_counter()
        result, retries_used = self._analyze_with_retry(data, pages_selection)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)

        doc = self._map_result(result, pages_selection)
        doc.provider_meta.update(
            {
                "model": self.model_id,
                "page_cap": self.page_cap or None,
                "pages_selection": pages_selection,
                "retries_used": retries_used,
                "duration_ms": duration_ms,
                "input_mime": mime_type,
            }
        )
        return doc

    # -- internals -----------------------------------------------------------

    def _analyze_with_retry(
        self, data: bytes, pages_selection: list[str] | None
    ) -> tuple[object, int]:
        """One analyze call with bounded exponential-backoff retries for
        transient failures. 429 (quota) is never retried; anything fatal
        propagates on the first occurrence."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return self._analyze_once(data, pages_selection), attempt
            except _TransientError as exc:
                last_exc = exc
            except Exception as exc:  # noqa: BLE001 — classified below
                kind = _classify(exc)
                if kind == "quota":
                    raise AzureDiQuotaExceededError(
                        "Azure Document Intelligence quota exceeded (HTTP 429). "
                        "The F0 free-tier monthly page budget is spent; raising "
                        "the tier or waiting for the quota reset is a human "
                        "decision — this pipeline never upgrades automatically."
                    ) from exc
                if kind == "transient":
                    last_exc = exc
                else:
                    raise
            if attempt < self.max_retries:
                time.sleep(self.backoff_base_seconds * (2**attempt))
        raise AzureDiTransientExhaustedError(
            f"Azure Document Intelligence stayed unavailable after "
            f"{self.max_retries + 1} attempts: {last_exc}"
        ) from last_exc

    def _analyze_once(self, data: bytes, pages_selection: list[str] | None) -> object:
        kwargs: dict = {}
        if pages_selection:
            kwargs["pages"] = pages_selection
        try:
            poller = self._client.begin_analyze_document(
                self.model_id, document=data, **kwargs
            )
            poller.wait(timeout=self.timeout_seconds)
            if not poller.done():
                raise AzureDiTimeoutError(
                    f"Azure Document Intelligence did not respond within "
                    f"{self.timeout_seconds} seconds."
                )
            return poller.result()
        except AzureDiTimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001 — classified by the retry loop
            status = _status_code(exc)
            if (status is not None and 500 <= status <= 599) or isinstance(
                exc, (ConnectionError, TimeoutError)
            ):
                raise _TransientError(str(exc)) from exc
            raise

    def _map_result(self, result: object, pages_selection) -> "object":  # noqa: ANN201
        from app.adapters.ocr.base import OcrBlock, OcrDocument, OcrPage

        pages_by_number: dict[int, OcrPage] = {}

        def page_for(number: int) -> OcrPage:
            page = pages_by_number.get(number)
            if page is None:
                page = OcrPage(page_number=number, blocks=[])
                pages_by_number[number] = page
            return page

        cap = self.page_cap
        pages_truncated = False
        for dp_page in getattr(result, "pages", None) or []:
            number = int(getattr(dp_page, "page_number", 0) or 0)
            if cap and number > cap:
                pages_truncated = True
                continue
            page = page_for(number)
            for line in getattr(dp_page, "lines", None) or []:
                bbox = _polygon_to_bbox(getattr(line, "polygon", None))
                page.blocks.append(
                    OcrBlock(
                        text=getattr(line, "content", "") or "",
                        bbox=bbox,
                        confidence=None,  # DI lines carry no confidence
                    )
                )

        for name, field in (getattr(result, "fields", None) or {}).items():
            regions = getattr(field, "bounding_regions", None) or []
            page_number = int(getattr(regions[0], "page_number", 1)) if regions else 1
            if cap and page_number > cap:
                pages_truncated = True
                continue
            field_name = AZURE_FIELD_MAP.get(name, _snake_case(name))
            content = getattr(field, "content", None)
            if not content:
                value = getattr(field, "value", None)
                content = "" if value is None else str(value)
            page = page_for(page_number)
            page.blocks.append(
                OcrBlock(
                    text=content,
                    bbox=_polygon_to_bbox(
                        getattr(regions[0], "polygon", None) if regions else None
                    ),
                    confidence=(
                        float(getattr(field, "confidence"))
                        if getattr(field, "confidence", None) is not None
                        else None
                    ),
                    field_hint=field_name,
                )
            )

        pages = [pages_by_number[k] for k in sorted(pages_by_number)]
        return OcrDocument(
            pages=pages,
            provider=self.name,
            provider_meta={
                "pages_truncated_to_cap": pages_truncated or None,
            },
            page_count=len(pages),
        )
