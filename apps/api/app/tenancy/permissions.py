"""Role-based authorization guards (the owner's role × action matrix).

Every domain route composes these dependencies; a role outside the allowed
set gets 403 ``forbidden`` (authenticated but not permitted — cross-org
access stays 404 per docs/API.md §5.4).

Matrix (docs/API.md §5):

- upload documents / create vendors, POs, invoices / run assessments /
  work cases: org_admin, finance_officer, reviewer
- verify / approve / reject / revoke bank accounts, approve or reject change
  requests, close cases: org_admin, reviewer
- view audit events: org_admin, auditor
- org/user administration: org_admin
"""

from collections.abc import Callable

from fastapi import Depends

from app.core.enums import UserRole
from app.core.errors import AppError, ErrorCode
from app.models import User
from app.tenancy.deps import get_current_user

FORBIDDEN_MESSAGE = "Your role is not permitted to perform this action."

# Role groups used by the domain routers.
CAN_CONTRIBUTE = (UserRole.ORG_ADMIN, UserRole.FINANCE_OFFICER, UserRole.REVIEWER)
CAN_VERIFY_ACCOUNTS = (UserRole.ORG_ADMIN, UserRole.REVIEWER)
CAN_VIEW_AUDIT = (UserRole.ORG_ADMIN, UserRole.AUDITOR)
ADMIN_ONLY = (UserRole.ORG_ADMIN,)


def require_roles(*allowed: UserRole) -> Callable[..., User]:
    """Dependency factory: allow only the given roles."""

    allowed_values = {role.value for role in allowed}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_values:
            raise AppError(ErrorCode.FORBIDDEN, FORBIDDEN_MESSAGE)
        return user

    return dependency
