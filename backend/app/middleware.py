"""One middleware for request ids, rate limiting and audit logging (in that order, so 429s are audited too)."""
import re
import time
import uuid

from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_config
from app.services import audit
from app.services.ratelimit import classify, limiter

_SAFE = re.compile(r"[^A-Za-z0-9._:-]")


def _clean(value: str, default: str, n: int = 64) -> str:
    return _SAFE.sub("", value or "")[:n] or default


class RequestGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cfg = get_config()
        start = time.perf_counter()
        rid = _clean(request.headers.get("x-request-id", ""), uuid.uuid4().hex[:16])
        request.state.request_id = rid
        # The socket peer only: X-Forwarded-For is client-controlled and would let anyone dodge the limit.
        ip = request.client.host if request.client else "unknown"
        method, path = request.method, request.url.path

        headers: dict[str, str] = {"X-Request-ID": rid}
        response = None
        if cfg.rate_limit_enabled and method != "OPTIONS" and path.startswith("/api/") and path != "/api/health":
            bucket = classify(method, path)
            limit = getattr(cfg, f"rate_limit_{bucket}")
            ok, remaining, retry = limiter.check((ip, bucket), limit, cfg.rate_limit_window)
            headers.update({"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining)})
            if not ok:
                headers["Retry-After"] = str(retry)
                response = JSONResponse(
                    status_code=429, headers=headers,
                    content={"detail": {"code": "RATE_LIMITED",
                                        "message": f"Too many {bucket} requests; retry in {retry}s."}})

        status = 429 if response is not None else 500   # 500 if call_next raises
        try:
            if response is None:
                response = await call_next(request)
                status = response.status_code
                for k, v in headers.items():
                    response.headers[k] = v
        finally:
            if audit.should_audit(method, path, status):
                route = request.scope.get("route")
                params = request.scope.get("path_params") or {}
                await run_in_threadpool(
                    audit.record, request_id=rid, actor=_clean(request.headers.get("x-actor", ""), "anonymous"),
                    client_ip=ip, method=method, route=(getattr(route, "path", None) or path)[:200], path=path[:500],
                    resource=("/".join(str(v) for v in params.values())[:200] or None), status_code=status,
                    outcome=audit.outcome_for(status), duration_ms=int((time.perf_counter() - start) * 1000))
        return response
