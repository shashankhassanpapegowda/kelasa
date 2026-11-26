"""Server-side payroll access.

Only role `admin` may read or change payroll. `sub_admin` is refused on every
payroll endpoint, including reads. Employees may view and download their own
published payslips and nothing else.
"""
from fastapi import HTTPException


class PayrollAccessError(HTTPException):
    def __init__(self, status_code: int, detail: str):
        super().__init__(status_code=status_code, detail=detail)


def require_payroll_admin(user: dict) -> dict:
    if not user or user.get("role") != "admin":
        raise PayrollAccessError(403, "Payroll is limited to administrators")
    return user


def require_own_payslip_access(user: dict) -> dict:
    """Employee self-service. Sub-admins are refused even for their own record."""
    if not user or user.get("role") == "sub_admin" or user.get("role") not in ("employee", "admin"):
        raise PayrollAccessError(403, "Payroll is limited to administrators")
    return user


def authorize_payslip(actor: dict, line: dict) -> dict:
    """Return the line when this person may see it. Draft and approved payslips
    are invisible to employees (404). Another employee's payslip is 403."""
    require_own_payslip_access(actor)
    if actor.get("role") == "admin":
        return line
    if line.get("user_id") != actor.get("user_id"):
        raise PayrollAccessError(403, "You can only view your own payslips")
    if line.get("status") != "published":
        raise PayrollAccessError(404, "Payslip not found")
    return line
