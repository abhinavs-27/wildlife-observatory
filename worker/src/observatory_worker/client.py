"""HTTP client for the edge job protocol."""

from __future__ import annotations

import httpx


class StaleClaim(Exception):
    """The edge rejected our claim token (lease expired and the job was re-claimed)."""


class EdgeClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60,
                 transport: httpx.BaseTransport | None = None):
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=timeout, transport=transport,
                                 headers={"Authorization": f"Bearer {token}"})

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code == 409:
            raise StaleClaim(r.text)
        r.raise_for_status()
        return r

    def claim(self, kinds: list[str], worker_id: str, capabilities: dict) -> dict | None:
        r = self._check(self.http.post("/jobs/claim", json={
            "kinds": kinds, "worker_id": worker_id, "capabilities": capabilities}))
        return None if r.status_code == 204 else r.json()

    def heartbeat(self, job_id: int, token: str) -> None:
        self._check(self.http.post(f"/jobs/{job_id}/heartbeat", json={"claim_token": token}))

    def worker_heartbeat(self, worker_id: str, kinds: list[str], info: dict) -> None:
        self._check(self.http.post("/workers/heartbeat", json={
            "worker_id": worker_id, "kinds": kinds, "info": info}))

    def download(self, url: str) -> bytes:
        return self._check(self.http.get(url)).content

    def upload_frames(self, job_id: int, token: str,
                      frames: list[tuple[int, float, bytes]]) -> dict[int, int]:
        files = [("files", (f"{i:05d}.jpg", data, "image/jpeg")) for i, _, data in frames]
        r = self._check(self.http.post(f"/jobs/{job_id}/frames", data={
            "claim_token": token,
            "indexes": ",".join(str(i) for i, _, _ in frames),
            "time_offsets": ",".join(f"{o:.3f}" for _, o, _ in frames)}, files=files))
        return {f["idx"]: f["frame_id"] for f in r.json()["frames"]}

    def result(self, job_id: int, payload: dict) -> dict:
        return self._check(self.http.post(f"/jobs/{job_id}/result", json=payload)).json()

    def fail(self, job_id: int, token: str, error: str, retryable: bool) -> None:
        self._check(self.http.post(f"/jobs/{job_id}/fail", json={
            "claim_token": token, "error": error, "retryable": retryable}))
