from fastmcp import FastMCP
import uvicorn
from starlette.responses import JSONResponse
import os
import json


mcp = FastMCP("my-tools")
from mcp_server import get_element_properties


@mcp.tool()
async def get_element_properties_tool(urn: str, objectId: int, viewName: str, token: str) -> str:
    """"
    
    Fetch detailed properties for a specific element including category, type, dimensions, material, system type, level, and custom parameters. Use when you need exact technical details about an element.
    
    urn: z.string().describe("Model URN (base64 encoded identifier) - it is ldocversionId or rdocversionId from clash data"),
    objectId: z.number().describe("Element database ID from clash data as number - it is loid or roid from clash data"),

    viewName: z.string().describe("View name of the model that has been loaded in the viewer - it is lviewableName or rviewableName from clash data"),
    access_token: z.string().describe("APS access token for authentication - from the context message")
    
    """

    result = await get_element_properties(
        urn,
        objectId,
        viewName,
        token
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))

    return f"Processed: {result}"

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "healthy"})

app = mcp.http_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
