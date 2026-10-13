from dotenv import load_dotenv

load_dotenv()

from mcp_server.server import mcp  # noqa: E402

mcp.run(transport="stdio")
