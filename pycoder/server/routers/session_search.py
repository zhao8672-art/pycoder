"""Session search API — FTS-based full-text search over chat history"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/search")
async def search_messages(
    q: str = Query("", description="Search query"),
    time: str = Query("all", description="Time filter: all/today/week/month"),
    limit: int = Query(50, le=100),
):
    """Search across session messages with keyword matching"""
    try:
        from pycoder.server.session_store import get_session_store
        store = get_session_store()
        sessions = store.list_sessions(limit=200)
        results = []

        import time as _time
        cutoff = _time.time()
        if time == "today":
            cutoff -= 86400
        elif time == "week":
            cutoff -= 604800
        elif time == "month":
            cutoff -= 2592000

        q_lower = q.lower()
        for s in sessions:
            if time != "all" and s.updated_at < cutoff:
                continue
            messages = store.get_messages(s.id, limit=100)
            for m in messages:
                if q_lower in m.content.lower():
                    results.append({
                        "sessionId": s.id,
                        "sessionTitle": s.title or s.id[:8],
                        "matchedContent": m.content[:200],
                        "timestamp": m.timestamp,
                        "role": m.role,
                    })
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break

        return {"results": results, "total": len(results)}
    except Exception as e:
        return {"results": [], "total": 0, "error": str(e)[:100]}
