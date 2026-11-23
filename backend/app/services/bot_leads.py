"""Customer bots save enquiries as rows in a Google Sheet tab with fixed columns."""
from __future__ import annotations

from datetime import datetime, timezone

LEAD_HEADERS = ["Received", "Name", "Contact", "Channel", "Details"]


async def append_lead(ctx, *, customer_name: str, details: str) -> None:
    from app.db.base import session_scope
    from app.services import google_sheets_service as sheets

    leads = ctx.settings.get("leads") or {}
    tab = (leads.get("tab") or "Leads").strip()[:60] or "Leads"
    row = [
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        customer_name.strip()[:120] or (ctx.contact_name or ""),
        ctx.contact_handle or "",
        ctx.platform,
        details.strip()[:2000],  # written RAW, so a leading "=" stays text, never a formula
    ]
    async with session_scope() as session:
        kw = dict(user_id=ctx.owner_user_id, organization_id=ctx.organization_id, session=session)
        spreadsheet_id = leads.get("spreadsheet_id") or await sheets.ensure_default_spreadsheet(**kw)
        tabs = await sheets.get_spreadsheet_metadata(**kw, spreadsheet_id=spreadsheet_id)
        titles = {s.get("properties", {}).get("title") for s in tabs.get("sheets") or []}
        quoted = "'" + tab.replace("'", "''") + "'"
        if tab not in titles:
            await sheets.create_sheet_tab(**kw, spreadsheet_id=spreadsheet_id, title=tab)
            await sheets.append_values(**kw, spreadsheet_id=spreadsheet_id, range_a1=f"{quoted}!A:E",
                                       values=[LEAD_HEADERS], value_input_option="RAW")
        await sheets.append_values(**kw, spreadsheet_id=spreadsheet_id, range_a1=f"{quoted}!A:E",
                                   values=[row], value_input_option="RAW")
