import asyncio
import threading

import httpx

from autosolid.api import create_app
from autosolid.projects import ProjectStore


def test_blocked_upload_does_not_block_health(tmp_path):
    store = ProjectStore(tmp_path / "data")
    app = create_app(store)
    service = app.state.service
    project = service.create_project("Event loop")
    original_add_source = service.add_source
    started = threading.Event()
    release = threading.Event()

    def blocked_add_source(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return original_add_source(*args, **kwargs)

    service.add_source = blocked_add_source

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            timeout=5,
        ) as client:
            timer = threading.Timer(1.0, release.set)
            timer.start()
            try:
                upload_task = asyncio.create_task(
                    client.post(
                        f"/api/v1/projects/{project.id}/sources",
                        params={"filename": "plano.pdf"},
                        content=b"%PDF-1.7\ntexto\n",
                    )
                )
                await asyncio.to_thread(started.wait)
                health_task = asyncio.create_task(
                    client.get("/api/v1/health")
                )
                done, _ = await asyncio.wait({health_task}, timeout=0.2)
                health_finished_before_release = (
                    health_task in done and not release.is_set()
                )
                release.set()
                upload_response = await upload_task
                health_response = await health_task
                assert upload_response.status_code == 201
                assert health_response.status_code == 200
                assert health_finished_before_release
            finally:
                timer.cancel()
                release.set()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        store.close()
