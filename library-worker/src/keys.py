"""IPNS key persistence — import/export keys via Firestore.

On first run, generates a dedicated IPNS key, exports it, and stores
both the raw key bytes and the IPNS name (peer ID) in Firestore.

On subsequent runs, imports the key from Firestore so the IPNS name
stays stable across container restarts.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

from common.config import settings
from common.db import get_ipns_key, store_ipns_key

logger = logging.getLogger("library-worker.keys")

KEY_NAME = settings.IPNS_LIBRARY_NAME  # default: "knowledge-library"


async def ensure_ipns_key() -> str:
    """Ensure the IPNS key exists locally. Returns the IPNS name (peer ID).

    1. Check if the key already exists locally (e.g. already imported).
    2. If not, try to import from Firestore.
    3. If not in Firestore either, generate a new one and export to Firestore.
    """
    # Check if key already exists locally
    existing = _list_local_keys()
    if KEY_NAME in existing:
        ipns_name = existing[KEY_NAME]
        logger.info(f"IPNS key '{KEY_NAME}' already exists locally: {ipns_name}")
        return ipns_name

    # Try to import from Firestore
    stored_key = get_ipns_key(KEY_NAME)
    if stored_key is not None:
        ipns_name = _import_key(KEY_NAME, stored_key)
        logger.info(f"IPNS key '{KEY_NAME}' imported from Firestore: {ipns_name}")
        return ipns_name

    # Generate new key, export to Firestore
    ipns_name = _generate_key(KEY_NAME)
    key_bytes = _export_key(KEY_NAME)
    store_ipns_key(KEY_NAME, key_bytes, ipns_name)
    logger.info(f"IPNS key '{KEY_NAME}' generated and stored in Firestore: {ipns_name}")

    # Also persist the IPNS name in the library state
    from common.db import get_library_state, update_library_state
    state = get_library_state()
    state.ipns_name = ipns_name
    update_library_state(state)

    return ipns_name


def _list_local_keys() -> dict[str, str]:
    """List IPFS keys. Returns {name: peer_id}."""
    result = subprocess.run(
        ["ipfs", "key", "list", "-l"],
        capture_output=True, text=True, timeout=10,
    )
    keys = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            # Format: "<peer_id> <name>"
            keys[parts[1]] = parts[0]
    return keys


def _generate_key(name: str) -> str:
    """Generate a new IPFS key. Returns the peer ID."""
    result = subprocess.run(
        ["ipfs", "key", "gen", name],
        capture_output=True, text=True, timeout=10,
    )
    result.check_returncode()
    return result.stdout.strip()


def _export_key(name: str) -> bytes:
    """Export an IPFS key as raw bytes."""
    with tempfile.NamedTemporaryFile(suffix=".key", delete=False) as f:
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["ipfs", "key", "export", name, "-o", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        result.check_returncode()
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _import_key(name: str, key_bytes: bytes) -> str:
    """Import an IPFS key from raw bytes. Returns the peer ID."""
    with tempfile.NamedTemporaryFile(suffix=".key", delete=False) as f:
        f.write(key_bytes)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["ipfs", "key", "import", name, tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        result.check_returncode()
        return result.stdout.strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)
