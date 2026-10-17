"""Dashboard stats route — org-scoped aggregates for the Overview cards."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routes import _domain_schemas as ds
from app.core.db import get_db
from app.models import User
from app.modules.stats import service as stats_service
from app.tenancy.deps import get_current_user

router = APIRouter(prefix="/stats", tags=["stats"])

_Db = Annotated[Session, Depends(get_db)]


@router.get("/dashboard", response_model=ds.DashboardStatsOut)
def dashboard_stats(
    db: _Db,
    actor: Annotated[User, Depends(get_current_user)],
) -> ds.DashboardStatsOut:
    """Headline counts for the caller's organization only.

    Read-only decision support: these numbers never assert that any invoice
    is genuine (R2) — ``needs_review_invoices``/``high_risk_invoices`` are
    work-queue sizes, not verdicts.
    """
    return ds.DashboardStatsOut(
        **stats_service.dashboard_counts(db, org_id=actor.organization_id)
    )
