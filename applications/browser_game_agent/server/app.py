"""
Browser Game Agent - FastAPI Server

Run from project root:
    uvicorn applications.browser_game_agent.server.app:app --port 8765
"""

import os
import sys
import uuid
import asyncio
import threading
import queue
import logging
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Load .env from app directory
_APP_DIR = Path(__file__).parent.parent
load_dotenv(_APP_DIR / ".env")

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from applications.browser_game_agent.workflow.pipeline import (
    run_generate_pipeline,
    run_modify_pipeline,
    run_ask_pipeline,
    DEFAULT_MODEL,
)

# ---- Paths ----
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
GAMES_DIR = BASE_DIR.parent / "assets" / "output" / "games"
GAMES_DIR.mkdir(parents=True, exist_ok=True)

# ---- Default API config from env ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")


def _get_default_api_config() -> dict:
    """Return default API config from env."""
    return {
        "api_key": OPENAI_API_KEY,
        "base_url": OPENAI_BASE_URL,
        "model": OPENAI_MODEL,
    }


# ---- App ----
app = FastAPI(title="Browser Game Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/games", StaticFiles(directory=str(GAMES_DIR), html=True), name="games")

# ---- In-memory session state ----
sessions: dict[str, dict] = {}
progress_queues: dict[str, queue.Queue] = {}
session_logs: dict[str, list] = {}  # session_id -> list of {stage, message, ts}

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")


# ---- Pydantic models ----
class GenerateRequest(BaseModel):
    task: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class ModifyRequest(BaseModel):
    modification_request: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class AskRequest(BaseModel):
    question: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


# ---- Helpers ----
def _progress_callback(session_id: str, stage: str, message: str):
    import datetime
    q = progress_queues.get(session_id)
    if q:
        q.put({"stage": stage, "message": message})
    if session_id in sessions:
        sessions[session_id]["last_stage"] = stage
        sessions[session_id]["last_message"] = message
    # Append to session log
    if session_id not in session_logs:
        session_logs[session_id] = []
    session_logs[session_id].append({
        "stage": stage,
        "message": message,
        "ts": datetime.datetime.now().strftime("%H:%M:%S"),
    })


def _coerce_report(v) -> str:
    """Coerce a test report value to a string (it may come back as dict/list from LLM)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    import json as _json
    return _json.dumps(v, ensure_ascii=False, indent=2)


def _sanitize_result(result: dict) -> dict:
    """Ensure test report fields are strings, not objects."""
    for key in ("ui_test_report", "functional_test_report"):
        if key in result:
            result[key] = _coerce_report(result[key])
    # Coerce boolean test-pass fields
    for key in ("ui_test_passed", "functional_test_passed"):
        if key in result and result[key] is not None:
            v = result[key]
            if isinstance(v, str):
                result[key] = v.lower() in ("true", "yes", "1", "pass", "passed")
    return result


def _game_url(session_id: str) -> Optional[str]:
    """Return the /games/... URL for a completed session, using the actual game_dir."""
    s = sessions.get(session_id, {})
    status = s.get("status")
    if status not in ("done", "error"):
        return None
    # Prefer cached game_url if already computed
    if s.get("game_url"):
        return s["game_url"]
    raw_game_dir = s.get("game_dir")
    if raw_game_dir:
        try:
            rel = Path(raw_game_dir).resolve().relative_to(GAMES_DIR.resolve())
            url = f"/games/{rel}/index.html"
            s["game_url"] = url
            return url
        except Exception:
            pass
    # Fallback to session_id-based path
    return f"/games/{session_id}/index.html"


def _run_generate(session_id: str, task: str, api_key: str, base_url: str, model_name: str):
    sessions[session_id]["status"] = "running"
    try:
        result = run_generate_pipeline(
            session_id=session_id,
            task=task,
            progress_callback=lambda stage, msg: _progress_callback(session_id, stage, msg),
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
        )
        result = _sanitize_result(result)
        sessions[session_id].update(result)
        sessions[session_id]["status"] = "done" if result.get("success") else "error"
        sessions[session_id]["tests_passed_early"] = result.get("tests_passed_early", False)
        if not result.get("success"):
            err = result.get("error", "Unknown pipeline error")
            sessions[session_id]["error"] = err
            _progress_callback(session_id, "error", err)
    except Exception as e:
        import traceback
        err = str(e)
        sessions[session_id]["status"] = "error"
        sessions[session_id]["error"] = err
        logging.error(f"[{session_id}] Unhandled error:\n{traceback.format_exc()}")
        _progress_callback(session_id, "error", err)
    finally:
        q = progress_queues.get(session_id)
        if q:
            q.put(None)


def _run_modify(session_id: str, modification_request: str, api_key: str, base_url: str, model_name: str):
    sessions[session_id]["status"] = "running"
    task = sessions[session_id].get("task", "")
    try:
        result = run_modify_pipeline(
            session_id=session_id,
            task=task,
            modification_request=modification_request,
            progress_callback=lambda stage, msg: _progress_callback(session_id, stage, msg),
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            game_dir=sessions[session_id].get("game_dir"),
        )
        result = _sanitize_result(result)
        sessions[session_id].update(result)
        sessions[session_id]["status"] = "done" if result.get("success") else "error"
        sessions[session_id]["tests_passed_early"] = result.get("tests_passed_early", False)
        if not result.get("success"):
            err = result.get("error", "Unknown pipeline error")
            sessions[session_id]["error"] = err
            _progress_callback(session_id, "error", err)
    except Exception as e:
        import traceback
        err = str(e)
        sessions[session_id]["status"] = "error"
        sessions[session_id]["error"] = err
        logging.error(f"[{session_id}] Unhandled error:\n{traceback.format_exc()}")
        _progress_callback(session_id, "error", err)
    finally:
        q = progress_queues.get(session_id)
        if q:
            q.put(None)


def _run_ask(session_id: str, question: str, api_key: str, base_url: str, model_name: str):
    sessions[session_id]["status"] = "asking"
    task = sessions[session_id].get("task", "")
    try:
        result = run_ask_pipeline(
            session_id=session_id,
            task=task,
            user_question=question,
            progress_callback=lambda stage, msg: _progress_callback(session_id, stage, msg),
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            game_dir=sessions[session_id].get("game_dir"),
        )
        sessions[session_id]["explanation"] = result.get("explanation", "")
        sessions[session_id]["status"] = "done" if result.get("success") else "error"
        if not result.get("success"):
            sessions[session_id]["error"] = result.get("error", "Unknown error")
    except Exception as e:
        import traceback
        err = str(e)
        sessions[session_id]["status"] = "error"
        sessions[session_id]["error"] = err
        logging.error(f"[{session_id}] Unhandled error:\n{traceback.format_exc()}")
    finally:
        q = progress_queues.get(session_id)
        if q:
            q.put(None)


# ---- Routes ----

@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task cannot be empty")

    # Resolve API config: user-provided > env defaults
    defaults = _get_default_api_config()
    api_key = req.api_key.strip() if req.api_key and req.api_key.strip() else defaults["api_key"]
    base_url = req.base_url.strip() if req.base_url and req.base_url.strip() else defaults["base_url"]
    model_name = req.model.strip() if req.model and req.model.strip() else defaults["model"]

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key required (set in .env or provide in request)")

    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
        "session_id": session_id,
        "task": req.task,
        "status": "pending",
        "model": model_name,
        "api_key": api_key,
        "base_url": base_url,
        "last_stage": None,
        "last_message": None,
        "game_plan": None,
        "game_code": None,
        "readme": None,
        "ui_test_passed": None,
        "ui_test_report": None,
        "functional_test_passed": None,
        "functional_test_report": None,
        "html_validation": None,
        "js_validation": None,
        "browser_test_results": None,
        "test_evidence": None,
        "structured_test_result": None,
        "explanation": None,
        "error": None,
    }
    progress_queues[session_id] = queue.Queue()

    t = threading.Thread(
        target=_run_generate,
        args=(session_id, req.task, api_key, base_url, model_name),
        daemon=True,
    )
    t.start()
    return {"session_id": session_id}


@app.post("/api/modify/{session_id}")
async def modify(session_id: str, req: ModifyRequest):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    if sessions[session_id].get("status") == "running":
        raise HTTPException(status_code=409, detail="Pipeline is still running")

    s = sessions[session_id]
    defaults = _get_default_api_config()
    api_key = (req.api_key.strip() if req.api_key and req.api_key.strip() else None) or s.get("api_key") or defaults["api_key"]
    base_url = (req.base_url.strip() if req.base_url and req.base_url.strip() else None) or s.get("base_url") or defaults["base_url"]
    model_name = (req.model.strip() if req.model and req.model.strip() else None) or s.get("model") or defaults["model"]

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key required")

    progress_queues[session_id] = queue.Queue()
    t = threading.Thread(
        target=_run_modify,
        args=(session_id, req.modification_request, api_key, base_url, model_name),
        daemon=True,
    )
    t.start()
    return {"session_id": session_id, "status": "running"}


@app.post("/api/ask/{session_id}")
async def ask(session_id: str, req: AskRequest):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    if sessions[session_id].get("status") == "running":
        raise HTTPException(status_code=409, detail="Pipeline is still running")

    s = sessions[session_id]
    defaults = _get_default_api_config()
    api_key = (req.api_key.strip() if req.api_key and req.api_key.strip() else None) or s.get("api_key") or defaults["api_key"]
    base_url = (req.base_url.strip() if req.base_url and req.base_url.strip() else None) or s.get("base_url") or defaults["base_url"]
    model_name = (req.model.strip() if req.model and req.model.strip() else None) or s.get("model") or defaults["model"]

    if not api_key:
        raise HTTPException(status_code=400, detail="api_key required")

    progress_queues[session_id] = queue.Queue()
    t = threading.Thread(
        target=_run_ask,
        args=(session_id, req.question, api_key, base_url, model_name),
        daemon=True,
    )
    t.start()
    return {"session_id": session_id, "status": "asking"}


@app.get("/api/code/{session_id}")
async def get_code(session_id: str):
    s = sessions.get(session_id, {})
    raw_game_dir = s.get("game_dir")
    game_dir = Path(raw_game_dir) if raw_game_dir else None
    if game_dir is None or not game_dir.exists():
        raise HTTPException(status_code=404, detail="Game files not found")

    files = []
    for path in sorted(game_dir.rglob("*")):
        if path.is_file() and path.name != "game_code" and not path.name.startswith("."):
            rel = path.relative_to(game_dir)
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                content = "<binary file>"
            files.append({"name": str(rel), "content": content, "size": path.stat().st_size})

    return {"session_id": session_id, "files": files}


@app.get("/api/log/{session_id}")
async def get_log(session_id: str):
    logs = session_logs.get(session_id, [])
    return {"session_id": session_id, "logs": logs}


@app.get("/api/status/{session_id}")
async def status(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    s = sessions[session_id]
    return {
        "session_id": session_id,
        "status": s.get("status"),
        "last_stage": s.get("last_stage"),
        "last_message": s.get("last_message"),
        "game_url": _game_url(session_id),
        "explanation": s.get("explanation"),
        "ui_test_passed": s.get("ui_test_passed"),
        "functional_test_passed": s.get("functional_test_passed"),
        "ui_test_report": s.get("ui_test_report"),
        "functional_test_report": s.get("functional_test_report"),
        "html_validation": s.get("html_validation"),
        "js_validation": s.get("js_validation"),
        "browser_test_results": s.get("browser_test_results"),
        "test_evidence": s.get("test_evidence"),
        "structured_test_result": s.get("structured_test_result"),
        "error": s.get("error"),
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if session_id not in sessions:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close()
        return

    q = progress_queues.get(session_id)
    if q is None:
        await websocket.send_json({"type": "error", "message": "No progress queue for session"})
        await websocket.close()
        return

    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                item = await loop.run_in_executor(None, lambda: q.get(timeout=30))
                if item is None:
                    s = sessions.get(session_id, {})
                    await websocket.send_json({
                        "type": "done",
                        "status": s.get("status", "done"),
                        "game_url": _game_url(session_id),
                        "ui_test_passed": s.get("ui_test_passed"),
                        "functional_test_passed": s.get("functional_test_passed"),
                        "ui_test_report": s.get("ui_test_report", ""),
                        "functional_test_report": s.get("functional_test_report", ""),
                        "html_validation": s.get("html_validation"),
                        "js_validation": s.get("js_validation"),
                        "browser_test_results": s.get("browser_test_results"),
                        "test_evidence": s.get("test_evidence"),
                        "structured_test_result": s.get("structured_test_result"),
                        "explanation": s.get("explanation"),
                        "tests_passed_early": s.get("tests_passed_early", False),
                        "error": s.get("error"),
                    })
                    break
                else:
                    await websocket.send_json({"type": "progress", **item})
            except queue.Empty:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "applications.browser_game_agent.server.app:app",
        host="0.0.0.0",
        port=8765,
        reload=False,
        log_level="info",
    )
