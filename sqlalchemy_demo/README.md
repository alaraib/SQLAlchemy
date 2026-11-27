# NetPulse

## Run

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs. Device and alert data is stored in the local `netpulse.db` SQLite file; restarting the server does not delete it.

## Logging

Application events are JSON. For example:

```json
{"event":"request_completed","level":"info","timestamp":"2026-11-27T12:00:00Z","request_id":"lab-trace-401","method":"PATCH","path":"/devices/{device_id}/status","status_code":200,"duration_ms":2.5}
```

`request_id` correlates events from one HTTP request; `device_id` identifies a device across requests. A valid `X-Request-ID` header is echoed in the response; otherwise the application generates one. Device IDs outside the supported safe logging format are redacted.

INFO records normal workflow and request completion, WARNING records handled domain errors, and ERROR records unexpected failures with sanitized stack frames. Status-change and offline-alert events are emitted when changes are staged, before the transaction commits; `device_registered` is emitted after commit.

Never log request bodies, passwords, tokens, connection URLs, or personal data. Logging redaction is a last-resort safety net for exact sensitive field names, not a substitute for safe logging. Do not log nested sensitive structures; nested values are not automatically redacted. Uvicorn's separate access and error logs may contain query strings or exception text, so protect those logs and avoid putting secrets in URLs or exception messages.

## ASGI And Database Access

Uvicorn is the ASGI server that runs `app.main:app`; FastAPI is the ASGI application it serves. ASGI supports asynchronous endpoints, such as an asynchronous simulated probe.

Synchronous SQLAlchemy lookups can block an async event loop. Prefer a synchronous `def` route for database lookups, or explicitly accept that trade-off in this small lab. This differs from the older synchronous WSGI interface, which does not natively support async endpoints.