#!/bin/bash
set -e

IPFS_PID=""
if [ -n "${IPFS_API_URL:-}" ] && [ "$IPFS_API_URL" != "http://127.0.0.1:5001/api/v0" ]; then
    echo "Using external IPFS API: $IPFS_API_URL"
    for i in $(seq 1 60); do
        if curl -s -o /dev/null "$IPFS_API_URL/id" 2>/dev/null; then
            echo "External IPFS API ready"
            break
        fi
        sleep 1
    done
else
    # Remove stale lock file if present (from previous crash)
    rm -f /root/.ipfs/repo.lock

    if [ ! -f /root/.ipfs/config ]; then
        ipfs init
    fi
    ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001
    ipfs config Addresses.Gateway /ip4/127.0.0.1/tcp/9080
    if [ "${IPFS_AUTO_ANNOUNCE_PUBLIC_IP:-false}" = "true" ]; then
        PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || true)"
        if [ -n "$PUBLIC_IP" ]; then
            echo "Announcing IPFS swarm address: /ip4/$PUBLIC_IP/tcp/4001"
            ipfs config --json Addresses.Announce "[\"/ip4/$PUBLIC_IP/tcp/4001\"]"
        else
            echo "WARNING: Unable to determine public IPFS announce address"
        fi
    fi

    # Reduce IPFS resource usage for embedded mode
    ipfs config --json Swarm.ConnMgr.LowWater 50
    ipfs config --json Swarm.ConnMgr.HighWater 100
    ipfs config --json Swarm.ConnMgr.GracePeriod '"30s"'
    ipfs config Reprovider.Interval "1h"
    ipfs config --json Swarm.DisableBandwidthMetrics true

    # Start IPFS daemon in background
    echo "Starting IPFS daemon..."
    ipfs daemon &
    IPFS_PID=$!

    # Wait for IPFS API to be fully ready (not just process start)
    echo "Waiting for IPFS API..."
    for i in $(seq 1 60); do
        if curl -s -o /dev/null http://127.0.0.1:5001/api/v0/id 2>/dev/null; then
            echo "IPFS daemon ready (PID: $IPFS_PID)"
            break
        fi
        if ! kill -0 $IPFS_PID 2>/dev/null; then
            echo "ERROR: IPFS daemon died"
            exit 1
        fi
        sleep 1
    done

    # Set IPFS API URL for the app (local embedded node)
    export IPFS_API_URL="http://127.0.0.1:5001/api/v0"
fi

# Run key initialization (import from Firestore or export to Firestore)
echo "Initializing IPNS key..."
python3 -c "
import asyncio
from src.keys import ensure_ipns_key
asyncio.run(ensure_ipns_key())
print('IPNS key initialized')
" || echo "WARNING: IPNS key init failed, will use ephemeral key"

if [ -n "$IPFS_PID" ]; then
    # Monitor IPFS daemon — restart if it dies
    (while true; do
        sleep 30
        if ! kill -0 $IPFS_PID 2>/dev/null; then
            echo "IPFS daemon died, restarting..."
            rm -f /root/.ipfs/repo.lock
            ipfs daemon &
            IPFS_PID=$!
            sleep 5
        fi
    done) &
fi

# Start the FastAPI application
echo "Starting Library Worker..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8080
