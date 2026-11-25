"""The MCP server: lets AI agents (MCP clients) work with a user's jobs,
companies and skills, much like the JSON API.

It runs as its own process, DJANGO_ROLE=mcp, with uvicorn serving
mcp_server.asgi:app (see the Dockerfile). Clients connect over Streamable
HTTP at settings.MCP_RESOURCE_URL and log in with OAuth 2.0: the web app is
the authorization server (accounts/oauth.py). The tools call the same
functions as the API (api/services/), so both apply the same rules.

The package isn't called `mcp`, which would hide the MCP SDK's package.
"""
