from fastmcp import FastMCP
import uvicorn
from starlette.responses import JSONResponse
import os

mcp = FastMCP("my-tools")

@mcp.tool()
async def example_tool(input_text: str) -> str:
    """An example tool that processes text"""
    return f"Processed: {input_text}"

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "healthy"})

app = mcp.http_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
