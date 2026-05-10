"""IPFS client supporting both Kubo RPC API and public HTTP gateway."""

import httpx

from .config import settings


def _api_url() -> str:
    return settings.IPFS_API_URL


def _gateway_url() -> str:
    return settings.IPFS_GATEWAY_URL.rstrip("/")


async def add_json(data: dict, *, name: str = "") -> str:
    """Add JSON data to IPFS via Kubo RPC, returns the CID."""
    import json

    content = json.dumps(data, default=str).encode()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_api_url()}/add",
            files={"file": (name or "data.json", content)},
            params={"pin": "true"},
        )
        resp.raise_for_status()
        return resp.json()["Hash"]


async def add_bytes(data: bytes, *, name: str = "file") -> str:
    """Add raw bytes to IPFS via Kubo RPC, returns the CID."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_api_url()}/add",
            files={"file": (name, data)},
            params={"pin": "true"},
        )
        resp.raise_for_status()
        return resp.json()["Hash"]


async def cat(cid: str) -> bytes:
    """Retrieve content from IPFS by CID.

    Tries the Kubo RPC API first. If IPFS_API_URL is empty or the request
    fails, falls back to the public HTTP gateway.
    """
    api = _api_url()
    if api:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{api}/cat",
                    params={"arg": cid},
                )
                resp.raise_for_status()
                return resp.content
        except (httpx.HTTPError, httpx.ConnectError):
            pass  # Fall through to gateway

    # Fallback: public IPFS HTTP gateway
    gateway = _gateway_url()
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(f"{gateway}/{cid}")
        resp.raise_for_status()
        return resp.content


async def cat_json(cid: str) -> dict:
    """Retrieve and parse JSON content from IPFS."""
    import json

    raw = await cat(cid)
    return json.loads(raw)


async def pin(cid: str) -> None:
    """Pin a CID to the local IPFS node."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{_api_url()}/pin/add",
            params={"arg": cid},
        )
        resp.raise_for_status()


async def unpin(cid: str) -> None:
    """Unpin a CID from the local IPFS node."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_api_url()}/pin/rm",
            params={"arg": cid},
        )
        resp.raise_for_status()


async def publish_ipns(cid: str, *, key: str = "self") -> str:
    """Publish a CID to IPNS under the given key. Returns the IPNS name."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_api_url()}/name/publish",
            params={
                "arg": f"/ipfs/{cid}",
                "key": key,
                "resolve": "true",
                "allow-offline": "false",
                "lifetime": "8760h",
                "ttl": "10s",
            },
        )
        resp.raise_for_status()
        return resp.json()["Name"]


async def resolve_ipns(name: str) -> str:
    """Resolve an IPNS name to its current CID."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_api_url()}/name/resolve",
            params={"arg": name},
        )
        resp.raise_for_status()
        path = resp.json()["Path"]  # e.g. /ipfs/Qm...
        return path.split("/ipfs/")[-1]


async def id_info() -> dict:
    """Get the IPFS node identity (peer ID, addresses, etc.)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_api_url()}/id")
        resp.raise_for_status()
        return resp.json()


async def swarm_peers() -> dict:
    """List connected IPFS swarm peers."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{_api_url()}/swarm/peers")
        resp.raise_for_status()
        return resp.json()
