from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import tool

from app.services.google_sheets_service import (
    GoogleOAuthError,
    batch_update,
    append_values,
    clear_values,
    create_sheet_tab,
    get_default_spreadsheet_id,
    get_spreadsheet_metadata,
    delete_dimension,
    delete_sheet_tab,
    insert_dimension,
    read_values,
    rename_sheet_tab,
    resize_sheet_grid,
    update_values,
)


def _build_header_map(headers: list[str]) -> dict[str, dict[str, Any]]:
    m: dict[str, dict[str, Any]] = {}
    for idx, h in enumerate(headers or [], start=1):
        key = str(h or "").strip().lower()
        if not key:
            continue
        m[key] = {"index": idx, "header": str(h)}
    return m
async def _resolve_sheet_tab(*, sid: str, preferred_tab: str | None, user_id: str) -> str:
    """Return a sheet tab name that exists.

    If preferred_tab is provided and exists, return it; otherwise return the first tab.
    """
    pref = (preferred_tab or "").strip()
    try:
        meta = await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=sid)
        titles = [
            (s.get("properties") or {}).get("title")
            for s in (meta.get("sheets") or [])
            if isinstance(s, dict)
        ]
        titles = [t for t in titles if isinstance(t, str) and t.strip()]
    except Exception:
        titles = []

    if pref and pref in titles:
        return pref
    if titles:
        return titles[0]
    return pref or "Sheet1"


def get_sheets_tools(*, user_id: str, chat_id: str | None = None):
    """Factory returning user-scoped LangChain tools for Google Sheets."""

    async def _get_headers_for_tab(*, sid: str, tab: str) -> dict:
        result = await read_values(user_id=user_id, spreadsheet_id=sid, range_a1=f"{tab}!A1:Z1")
        values = (result.get("values") or []) if isinstance(result, dict) else []
        headers: list[str] = []
        if values and isinstance(values, list) and values[0] and isinstance(values[0], list):
            headers = [str(h).strip() for h in values[0] if str(h).strip()]
        header_map = _build_header_map(headers)
        return {"headers": headers, "header_map": header_map}

    @tool("sheets_list_tabs")
    async def sheets_list_tabs(spreadsheet_id: str | None = None) -> dict:
        """List the sheet tabs (worksheets) inside a spreadsheet.

        When to use:
        - Use this before reading/writing if you are not sure which tab exists.
        - Use this to avoid guessing a tab name.

        Args:
            spreadsheet_id: Optional. The spreadsheet ID (the long ID from the Google Sheets URL).
                If omitted, the user's configured default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - spreadsheet_id: str (resolved)
            - tabs: list[str] (tab titles)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            meta = await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=sid)
            titles = [
                (s.get("properties") or {}).get("title")
                for s in (meta.get("sheets") or [])
                if isinstance(s, dict)
            ]
            titles = [t for t in titles if isinstance(t, str) and t.strip()]
            return {"ok": True, "spreadsheet_id": sid, "tabs": titles}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_read_range")
    async def sheets_read_range(range_a1: str, spreadsheet_id: str | None = None) -> dict:
        """Read values from a spreadsheet range (A1 notation).

        This reads *values only* (not formatting).

        Args:
            range_a1: Required. A1 notation including the tab name.
                Examples:
                - "Expenses!A1:F50" (rectangular range)
                - "Sheet1!A:A" (entire column A)
                - "Sheet1!1:1" (entire row 1)
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (Google Sheets API value range response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await read_values(user_id=user_id, spreadsheet_id=sid, range_a1=range_a1)
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_get_headers")
    async def sheets_get_headers(sheet_name: str | None = None, spreadsheet_id: str | None = None) -> dict:
        """Fetch the header row (row 1) for a sheet tab and build a lookup map.

        Use this to *ground column selection* before you update/append data.

        Args:
            sheet_name: Optional. The tab title. If omitted or invalid, the first available tab is used.
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - sheet_name: str (resolved tab title)
            - headers: list[str]
            - header_map: dict[str, {index:int, header:str}]
              where key is the lowercased header text and index is 1-based column index.
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}

            tab = await _resolve_sheet_tab(sid=sid, preferred_tab=sheet_name, user_id=user_id)
            parsed = await _get_headers_for_tab(sid=sid, tab=tab)
            return {"ok": True, "sheet_name": tab, "headers": parsed["headers"], "header_map": parsed["header_map"]}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_get_metadata")
    async def sheets_get_metadata(spreadsheet_id: str | None = None) -> dict:
        """Get spreadsheet metadata (spreadsheet title + tabs + grid sizes).

        Args:
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - spreadsheet_id: str
            - title: str
            - sheets: list[str] (tab titles)
            - error: str (present only when ok=false)

        Notes:
            This is a *lightweight* metadata call (fields are restricted in the service).
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await get_spreadsheet_metadata(user_id=user_id, spreadsheet_id=sid)
            sheets = [s.get("properties", {}).get("title") for s in result.get("sheets", [])]
            return {
                "ok": True,
                "spreadsheet_id": result.get("spreadsheetId"),
                "title": (result.get("properties") or {}).get("title"),
                "sheets": [s for s in sheets if s],
            }
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_append_values")
    async def sheets_append_values(
        range_a1: str,
        values: list[list[Any]],
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Append one or more rows to the end of a table/range.

        This uses the Sheets `values.append` endpoint and inserts new rows.

        Args:
            range_a1: Required. A1 notation including tab and columns.
                Best practice is to specify only columns (not a fixed row), e.g.:
                - "Expenses!A:F"
                - "Sheet1!A:D"
            values: Required. 2D array of rows. Each inner list is a row.
                Example: [["2026-01-01", "Vendor", 123.45]]
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.
            value_input_option: Optional. How input is interpreted by Sheets.
                Allowed values:
                - "USER_ENTERED" (default): parse numbers/dates/formulas as if typed
                - "RAW": store exactly as provided

        Returns:
            A dict with:
            - ok: bool
            - data: dict (Sheets API append response; includes updates.updatedRange)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}

            result = await append_values(
                user_id=user_id,
                spreadsheet_id=sid,
                range_a1=range_a1,
                values=values,
                value_input_option=value_input_option,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_update_values")
    async def sheets_update_values(
        range_a1: str,
        values: list[list[Any]],
        spreadsheet_id: str | None = None,
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Overwrite values in an exact A1 range (in-place update).

        Use this when you know the exact cells to overwrite.

        Args:
            range_a1: Required. Exact range to overwrite.
                Examples:
                - "Expenses!A2:F2" (one row)
                - "Sheet1!B2:D10" (block)
            values: Required. 2D array sized to match the target range.
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.
            value_input_option: Optional. "USER_ENTERED" (default) or "RAW".

        Returns:
            A dict with:
            - ok: bool
            - data: dict (Sheets API update response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}

            result = await update_values(
                user_id=user_id,
                spreadsheet_id=sid,
                range_a1=range_a1,
                values=values,
                value_input_option=value_input_option,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_clear_values")
    async def sheets_clear_values(range_a1: str, spreadsheet_id: str | None = None) -> dict:
        """Clear values in a specific A1 range (does not delete rows/columns).

        This removes cell contents but keeps the grid structure.

        Args:
            range_a1: Required. A1 range including tab name.
                Example: "Expenses!A2:F100".
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (Sheets API clear response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}

            result = await clear_values(
                user_id=user_id,
                spreadsheet_id=sid,
                range_a1=range_a1,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_batch_update")
    async def sheets_batch_update(
        requests: list[dict[str, Any]],
        spreadsheet_id: str | None = None,
        include_spreadsheet_in_response: bool = False,
        response_include_grid_data: bool = False,
    ) -> dict:
        """Run an arbitrary Google Sheets `spreadsheets.batchUpdate` request.

        This is the most powerful tool. It can modify tabs, formatting, merges, dimensions,
        protections, etc.

        Args:
            requests: Required. A list of Google Sheets API BatchUpdate request objects.
                Each item must match one of the documented request types.
                Example (create a tab):
                [{"addSheet": {"properties": {"title": "NewTab"}}}]
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.
            include_spreadsheet_in_response: Optional. If true, include spreadsheet object in response.
            response_include_grid_data: Optional. If true, include grid data in response (can be large).

        Returns:
            A dict with:
            - ok: bool
            - data: dict (Sheets API batchUpdate response)
            - error: str (present only when ok=false)

        Notes:
            Prefer the specialized tools (create/rename/delete tab, insert/delete rows/cols, resize grid)
            when possible because they are simpler and less error-prone.
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await batch_update(
                user_id=user_id,
                spreadsheet_id=sid,
                requests=requests,
                include_spreadsheet_in_response=include_spreadsheet_in_response,
                response_include_grid_data=response_include_grid_data,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_create_tab")
    async def sheets_create_tab(title: str, spreadsheet_id: str | None = None) -> dict:
        """Create a new sheet tab (worksheet) in the spreadsheet.

        Args:
            title: Required. New tab name (must be unique within the spreadsheet).
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (batchUpdate response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await create_sheet_tab(user_id=user_id, spreadsheet_id=sid, title=title)
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_rename_tab")
    async def sheets_rename_tab(sheet_name: str, new_title: str, spreadsheet_id: str | None = None) -> dict:
        """Rename an existing sheet tab.

        Args:
            sheet_name: Required. Existing tab title.
            new_title: Required. New tab title.
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (batchUpdate response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await rename_sheet_tab(user_id=user_id, spreadsheet_id=sid, sheet_title=sheet_name, new_title=new_title)
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_delete_tab")
    async def sheets_delete_tab(sheet_name: str, spreadsheet_id: str | None = None) -> dict:
        """Delete a sheet tab.

        Warning: This deletes the entire worksheet and all its data.

        Args:
            sheet_name: Required. Tab title to delete.
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (batchUpdate response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await delete_sheet_tab(user_id=user_id, spreadsheet_id=sid, sheet_title=sheet_name)
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_resize_grid")
    async def sheets_resize_grid(
        sheet_name: str,
        row_count: int | None = None,
        column_count: int | None = None,
        spreadsheet_id: str | None = None,
    ) -> dict:
        """Resize the grid size (row/column count) for a tab.

        This changes the *maximum* rows/columns available in that sheet.

        Args:
            sheet_name: Required. Tab title.
            row_count: Optional. New total row count (not an increment).
            column_count: Optional. New total column count (not an increment).
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (batchUpdate response)
            - error: str (present only when ok=false)

        Notes:
            You must provide at least one of row_count or column_count.
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await resize_sheet_grid(
                user_id=user_id,
                spreadsheet_id=sid,
                sheet_title=sheet_name,
                row_count=row_count,
                column_count=column_count,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_insert_dimension")
    async def sheets_insert_dimension(
        sheet_name: str,
        dimension: str,
        start_index: int,
        end_index: int,
        inherit_from_before: bool = False,
        spreadsheet_id: str | None = None,
    ) -> dict:
        """Insert rows or columns into a sheet.

        Indexing details:
        - Uses 0-based indices.
        - The range is [start_index, end_index) (end is exclusive).
        - For example, to insert 1 row at row 2 (human row number 2), use start_index=1, end_index=2.

        Args:
            sheet_name: Required. Tab title.
            dimension: Required. Either "ROWS" or "COLUMNS".
            start_index: Required. 0-based start index (inclusive).
            end_index: Required. 0-based end index (exclusive).
            inherit_from_before: Optional. If true, new rows/cols inherit formatting from the previous row/col.
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (batchUpdate response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await insert_dimension(
                user_id=user_id,
                spreadsheet_id=sid,
                sheet_title=sheet_name,
                dimension=dimension,
                start_index=start_index,
                end_index=end_index,
                inherit_from_before=inherit_from_before,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    @tool("sheets_delete_dimension")
    async def sheets_delete_dimension(
        sheet_name: str,
        dimension: str,
        start_index: int,
        end_index: int,
        spreadsheet_id: str | None = None,
    ) -> dict:
        """Delete rows or columns from a sheet.

        Indexing details:
        - Uses 0-based indices.
        - The range is [start_index, end_index) (end is exclusive).
        - Example: to delete the first row, start_index=0, end_index=1.

        Args:
            sheet_name: Required. Tab title.
            dimension: Required. Either "ROWS" or "COLUMNS".
            start_index: Required. 0-based start index (inclusive).
            end_index: Required. 0-based end index (exclusive).
            spreadsheet_id: Optional. Spreadsheet ID. If omitted, the default spreadsheet is used.

        Returns:
            A dict with:
            - ok: bool
            - data: dict (batchUpdate response)
            - error: str (present only when ok=false)
        """
        try:
            sid = spreadsheet_id or await get_default_spreadsheet_id(user_id)
            if not sid:
                return {"ok": False, "error": "No default spreadsheet configured. Connect Google Sheets again."}
            result = await delete_dimension(
                user_id=user_id,
                spreadsheet_id=sid,
                sheet_title=sheet_name,
                dimension=dimension,
                start_index=start_index,
                end_index=end_index,
            )
            return {"ok": True, "data": result}
        except GoogleOAuthError as e:
            return {"ok": False, "error": str(e)}

    return [
        sheets_list_tabs,
        sheets_read_range,
        sheets_get_headers,
        sheets_get_metadata,
        sheets_append_values,
        sheets_update_values,
        sheets_clear_values,
        sheets_batch_update,
        sheets_create_tab,
        sheets_rename_tab,
        sheets_delete_tab,
        sheets_resize_grid,
        sheets_insert_dimension,
        sheets_delete_dimension,
    ]
