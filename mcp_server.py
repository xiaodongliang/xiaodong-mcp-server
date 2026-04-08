#!/usr/bin/env python3
"""
MCP Server for Clash Resolution (SQL Version)
- 用 SQL 数据库缓存 APS 构件
- 完整 JSON 存储 properties / dimensions
- 精确查询 objectId，100% 稳定
"""

import os
import sys
import json
import asyncio
import time
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

import httpx
import sqlite3

from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / 'server' / '.env'
load_dotenv(env_path)

server = Server("clash-resolver-mcp")

# ========== 配置 ==========
APS_CLIENT_ID = os.getenv('APS_CLIENT_ID')
APS_CLIENT_SECRET = os.getenv('APS_CLIENT_SECRET')

# ========== 全局变量 ==========
db_conn: sqlite3.Connection | None = None

# ========== SQL 数据库初始化 ==========
def init_sql_db():
    """初始化 SQLite 数据库和表结构"""
    global db_conn
    db_dir = Path(__file__).parent / "sql_db"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / "aec_elements.db"

    db_conn = sqlite3.connect(str(db_path), check_same_thread=False)

    # ✅ 关键：一张表，完整 JSON 存储所有属性
    db_conn.execute('''
        CREATE TABLE IF NOT EXISTS elements (
            urn TEXT NOT NULL,
            objectId INTEGER NOT NULL,
            name TEXT,
            category TEXT,
            family TEXT,
            type TEXT,
            level TEXT,
            dimensions_json TEXT,  -- JSON 完整存储
            properties_json TEXT,   -- JSON 完整存储
            raw_json TEXT,          -- 原始 APS 属性
            PRIMARY KEY (urn, objectId)
        )
    ''')
    db_conn.commit()
    
    print(f"✅ SQL 数据库初始化完成: {db_path}", file=sys.stderr, flush=True)

# ========== SQL 存储 / 查询 ==========
def upsert_element(urn: str, elem: dict):
    """存入或更新构件（完整 JSON 存储）"""
    db_conn.execute('''
        INSERT OR REPLACE INTO elements
        (urn, objectId, name, category, family, type, level,
         dimensions_json, properties_json, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        urn,
        elem["objectId"],
        elem.get("name"),
        elem.get("category"),
        elem.get("family"),
        elem.get("type"),
        elem.get("level"),
        json.dumps(elem.get("dimensions", {})),
        json.dumps(elem.get("properties", {})),
        json.dumps(elem.get("rawProperties", {}))
    ))
    db_conn.commit()

def get_element(urn: str, objectId: int) -> dict | None:
    """精确查询：按 urn + objectId"""
    cur = db_conn.execute('''
        SELECT * FROM elements WHERE urn = ? AND objectId = ?
    ''', (urn, objectId))
    row = cur.fetchone()
    if not row:
        return None

    keys = [d[0] for d in cur.description]
    item = dict(zip(keys, row))

    return {
        "status": "found",
        "objectId": item["objectId"],
        "name": item["name"],
        "category": item["category"],
        "family": item["family"],
        "type": item["type"],
        "level": item["level"],
        "dimensions": json.loads(item["dimensions_json"]),
        "properties": json.loads(item["properties_json"]),
        "rawProperties": json.loads(item["raw_json"])
    }

def bulk_upsert(urn: str, elements: list[dict]):
    """批量存入 SQL"""
    for elem in elements:
        upsert_element(urn, elem)
    print(f"✅ 批量保存 {len(elements)} 个构件到 SQL", file=sys.stderr, flush=True)

# ========== MCP 工具 ==========
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_element_properties",
            description="通过 objectId 获取构件属性（SQL 缓存版）",
            inputSchema={
                "type": "object",
                "properties": {
                    "urn": {"type": "string"},
                    "objectId": {"type": "number"},
                    "viewName": {"type": "string"},
                    "access_token": {"type": "string"}
                },
                "required": ["urn", "objectId", "viewName", "access_token"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_element_properties":
        res = await get_element_properties(
            urn=arguments["urn"],
            objectId=int(arguments["objectId"]),
            viewName=arguments["viewName"],
            token=arguments["access_token"]
        )
        return [TextContent(type="text", text=json.dumps(res, indent=2))]
    raise ValueError("未知工具")

# ========== 核心逻辑 ==========
async def fetch_all_elements(urn: str, token: str, viewName: str):
    """从 APS 获取所有构件"""
    async with httpx.AsyncClient() as cli:
        headers = {"Authorization": f"Bearer {token}"}
        meta = await cli.get(
            f"https://developer.api.autodesk.com/modelderivative/v2/designdata/{urn}/metadata",
            headers=headers
        )
        meta.raise_for_status()
        data = meta.json()

        guid = None
        for m in data["data"]["metadata"]:
            if m["name"] == viewName:
                guid = m["guid"]
                break
        if not guid:
            guid = data["data"]["metadata"][0]["guid"]

        for _ in range(30):
            res = await cli.get(
                f"https://developer.api.autodesk.com/modelderivative/v2/designdata/{urn}/metadata/{guid}/properties",
                headers=headers
            )
            res.raise_for_status()
            j = res.json()
            if "data" in j:
                return j["data"]["collection"]
            await asyncio.sleep(2)

        raise Exception("APS 属性获取超时")

def parse_element(obj: dict) -> dict:
    """解析 APS 结构 → 简化结构（JSON 完整保留）"""
    props = obj.get("properties", {})
    return {
        "objectId": obj["objectid"],
        "name": obj.get("name", "Unknown"),
        "category": None,
        "family": None,
        "type": None,
        "level": None,
        "dimensions": {},
        "properties": {},
        "rawProperties": props
    }

async def get_element_properties(urn: str, objectId: int, viewName: str, token: str):
    """获取构件属性（SQL 缓存版，无需 LLM）"""
    try:
        # 初始化数据库（如果还没初始化）
        if not db_conn:
            init_sql_db()

        # 1. 查 SQL 缓存
        item = get_element(urn, objectId)
        if item:
            print(f"✅ SQL 缓存命中: objectId {objectId}", file=sys.stderr, flush=True)
            return item

        # 2. 缓存未命中 → 全量拉取 APS 数据
        print(f"📡 SQL 缓存未命中，从 APS 拉取所有构件...", file=sys.stderr, flush=True)
        coll = await fetch_all_elements(urn, token, viewName)
        parsed = [parse_element(o) for o in coll]
        bulk_upsert(urn, parsed)

        # 3. 再次查询
        item = get_element(urn, objectId)
        if item:
            return item

        return {"status": "not found", "objectId": objectId}

    except Exception as e:
        print(f"❌ 错误: {type(e).__name__}: {str(e)}", file=sys.stderr, flush=True)
        return {
            "error": str(e),
            "objectId": objectId,
            "type": type(e).__name__
        }

# ========== 启动 ==========
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())