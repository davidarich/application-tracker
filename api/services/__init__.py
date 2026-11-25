"""What the JSON API and the MCP server do, for a given user.

The API's routers (api/routers/) and the MCP server's tools (mcp_server/)
are thin wrappers over these functions, so both apply the same rules: the
web app's forms, the ownership checks in tracker/ownership.py, and so on.

They raise FieldErrors (invalid fields), Http404 (no such record, or not the
user's), ninja's HttpError (e.g. 403 for staff-only changes) and, rarely,
IntegrityError (a clash with a record saved at the same moment); each caller
turns those into its own kind of error.
"""
