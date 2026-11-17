"""
LYRA — Web Search Tool (Odysseus-inspired)
Real-time web search using Groq Compound Beta model.
"""

import logging
import httpx
from config import settings

logger = logging.getLogger("LYRA.WebSearch")


async def web_search(query: str = "", **kwargs) -> dict:
    """Search the web using Groq's compound-beta model with built-in search."""
    if not query:
        return {"result": "❌ No search query provided.", "success": False}
    
    if not settings.GROQ_API_KEY:
        return {"result": "❌ Groq API key not configured.", "success": False}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                },
                json={
                    "model": "compound-beta",
                    "messages": [
                        {"role": "system", "content": "Search the web and provide accurate, up-to-date information. Cite sources."},
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            logger.info(f"🔍 Web search complete: {query[:50]}...")
            return {"result": content, "success": True}
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return {"result": f"❌ Search error: {str(e)}", "success": False}
