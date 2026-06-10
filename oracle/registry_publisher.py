from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class RegistryPublisher:
    def __init__(self) -> None:
        self._token = os.getenv("PRISM_GITHUB_TOKEN", "")
        self._repo = os.getenv("PRISM_REGISTRY_REPO", "arpjw/prism")
        self._branch = os.getenv("PRISM_REGISTRY_BRANCH", "main")
        self._path = os.getenv("PRISM_REGISTRY_PATH", "registry/registry.json")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def fetch_registry(self) -> tuple[dict, str]:
        url = f"{GITHUB_API}/repos/{self._repo}/contents/{self._path}?ref={self._branch}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]

    async def publish_scores(
        self,
        scores: dict[str, float],
        labels: dict[str, str],
    ) -> bool:
        if not self._token:
            logger.info("PRISM_GITHUB_TOKEN not set — skipping registry publish")
            return False

        try:
            registry, sha = await self.fetch_registry()
        except Exception as exc:
            logger.error("failed to fetch registry for publishing: %s", exc)
            return False

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        updated = False

        connectors = registry.get("connectors", [])
        if isinstance(connectors, list):
            for connector in connectors:
                slug = connector.get("slug")
                if slug and slug in scores:
                    connector["reputation_score"] = scores[slug]
                    connector["reputation_label"] = labels.get(slug, "UNKNOWN")
                    connector["scores_updated_at"] = now_iso
                    updated = True
        elif isinstance(connectors, dict):
            for slug, connector in connectors.items():
                if slug in scores:
                    connector["reputation_score"] = scores[slug]
                    connector["reputation_label"] = labels.get(slug, "UNKNOWN")
                    connector["scores_updated_at"] = now_iso
                    updated = True

        if not updated:
            logger.info("no matching connectors in registry — nothing to publish")
            return True

        content_bytes = json.dumps(registry, indent=2).encode("utf-8")
        encoded = base64.b64encode(content_bytes).decode("utf-8")

        url = f"{GITHUB_API}/repos/{self._repo}/contents/{self._path}"
        payload = {
            "message": f"oracle: update reputation scores ({now_iso})",
            "content": encoded,
            "sha": sha,
            "branch": self._branch,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(url, headers=self._headers(), json=payload)
                if resp.status_code not in (200, 201):
                    logger.error(
                        "registry publish failed HTTP %s: %s",
                        resp.status_code,
                        resp.text[:500],
                    )
                    return False
                return True
        except Exception as exc:
            logger.error("registry publish exception: %s", exc)
            return False

    async def check_auth(self) -> bool:
        if not self._token:
            return False
        try:
            url = f"{GITHUB_API}/repos/{self._repo}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code != 200:
                    return False
                data = resp.json()
                perms = data.get("permissions", {})
                return bool(perms.get("push", False))
        except Exception:
            return False
