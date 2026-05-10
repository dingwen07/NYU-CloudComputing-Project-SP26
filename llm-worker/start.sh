#!/bin/bash
set -e

# Remove stale lock file if present (from previous container exit)
rm -f /root/.ipfs/repo.lock

if [ ! -f /root/.ipfs/config ]; then
    ipfs init
fi
ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001
ipfs config Addresses.Gateway /ip4/127.0.0.1/tcp/9080

# Reduce IPFS resource usage for embedded mode
ipfs config --json Swarm.ConnMgr.LowWater 50
ipfs config --json Swarm.ConnMgr.HighWater 100
ipfs config --json Swarm.ConnMgr.GracePeriod '"30s"'
ipfs config Reprovider.Interval "0"
ipfs config --json Swarm.DisableBandwidthMetrics true

# Start IPFS daemon in background (read-only use)
echo "Starting IPFS daemon..."
ipfs daemon &
IPFS_PID=$!

# Wait for IPFS API to be fully ready
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

# Set IPFS API URL for the app
export IPFS_API_URL="http://127.0.0.1:5001/api/v0"

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

# Start the FastAPI application
echo "Starting LLM Worker..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8080
