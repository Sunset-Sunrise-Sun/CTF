import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from .models import Challenge, ChallengeCreate, Event, NoteCreate
from .store import Store
from .workspace import Workspace


def create_app(data_root: Path | None = None) -> FastAPI:
    root = data_root or Path(os.environ.get("CTF_DATA_DIR", "../.local-data"))

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(root / "workbench.sqlite3")
        app.state.workspace = Workspace(root / "challenges")
        yield

    app = FastAPI(title="CTF Agent Workbench", version="0.1.0", lifespan=lifespan)

    def exists(cid):
        try:
            return app.state.store.get(cid)
        except KeyError:
            raise HTTPException(404, "Challenge not found") from None

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "execution_enabled": False,
            "model_network_enabled": False,
        }

    @app.get("/api/challenges", response_model=list[Challenge])
    def challenges():
        return app.state.store.challenges()

    @app.post("/api/challenges", response_model=Challenge, status_code=201)
    def create(body: ChallengeCreate):
        challenge = Challenge(**body.model_dump())
        app.state.workspace.challenge(challenge.challenge_id).mkdir()
        app.state.store.create(challenge)
        return challenge

    @app.get("/api/challenges/{cid}/events", response_model=list[Event])
    def events(cid: str):
        exists(cid)
        return app.state.store.events(cid)

    @app.post("/api/challenges/{cid}/notes", response_model=Event, status_code=201)
    def note(cid: str, body: NoteCreate):
        exists(cid)
        if body.correction_of and body.correction_of not in {
            e.event_id for e in app.state.store.events(cid)
        }:
            raise HTTPException(422, "Correction must reference an existing event")
        return app.state.store.append(cid, "user", "note", body.model_dump())

    @app.get("/api/challenges/{cid}/integrity")
    def integrity(cid: str):
        exists(cid)
        return app.state.store.verify(cid)

    @app.get("/api/tools")
    def tools():
        return {"tools": [], "execution_enabled": False, "max_active_containers": 3}

    return app


app = create_app()
