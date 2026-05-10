#!/usr/bin/env python3
"""End-to-end workflow test for the IAN Knowledge Management Framework.

Usage:
    python scripts/test_workflow.py

Requires all services running (via docker-compose up).
"""

import json
import sys
import time

import httpx

API_BASE = "http://localhost:8000"
IPFS_API = "http://localhost:5001/api/v0"


def step(msg: str):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def main():
    # 1. Health checks
    step("1. Checking service health")
    for name, port in [("api-server", 8000), ("orchestrator", 8001), ("llm-worker", 8002), ("library-worker", 8003)]:
        try:
            r = httpx.get(f"http://localhost:{port}/health", timeout=5)
            print(f"  {name}: {r.json()}")
        except Exception as e:
            print(f"  {name}: FAILED - {e}")

    # 2. Add test content to IPFS
    step("2. Adding test content to IPFS")
    test_doc = """# Introduction to Cloud Computing

Cloud computing is the delivery of computing services over the internet.
These services include servers, storage, databases, networking, software,
analytics, and intelligence. Cloud computing offers faster innovation,
flexible resources, and economies of scale.

Key benefits include:
- Cost reduction through pay-as-you-go pricing
- Global scale and elasticity
- Increased speed and agility
- Enhanced security and reliability
"""

    r = httpx.post(
        f"{IPFS_API}/add",
        files={"file": ("test-doc.md", test_doc.encode())},
        params={"pin": "true"},
        timeout=15,
    )
    cid = r.json()["Hash"]
    print(f"  Content pinned with CID: {cid}")

    # 3. Submit job
    step("3. Submitting job to API server")
    r = httpx.post(
        f"{API_BASE}/api/jobs",
        json={"cid": cid, "title": "Introduction to Cloud Computing"},
        timeout=10,
    )
    job = r.json()
    job_id = job["id"]
    print(f"  Job created: {job_id}")
    print(f"  Status: {job['status']}")

    # 4. Wait for processing
    step("4. Waiting for job to be processed...")
    for i in range(30):
        time.sleep(5)
        r = httpx.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10)
        job = r.json()
        print(f"  [{i*5}s] Status: {job['status']}")

        if job["status"] == "PENDING_REVIEW":
            print("  Job is ready for review!")
            break
        elif job["status"] in ("FAILED", "CANCELLED"):
            print(f"  Job failed with status: {job['status']}")
            sys.exit(1)
    else:
        print("  Timeout waiting for processing")
        sys.exit(1)

    # 5. Show AI metadata
    step("5. AI-generated metadata")
    if job.get("ai_metadata"):
        meta = job["ai_metadata"]
        print(f"  Summary: {meta['summary']}")
        print(f"  Category: {meta['category']}")
        print(f"  Tags: {meta['tags']}")
        print(f"  Key Concepts: {meta['key_concepts']}")

    # 6. Approve the job
    step("6. Approving job (human-in-the-loop)")
    r = httpx.post(
        f"{API_BASE}/api/review/{job_id}",
        json={"action": "approve", "reviewer_notes": "Looks good!"},
        timeout=10,
    )
    print(f"  Review result: {r.json()}")

    # 7. Wait for publishing
    step("7. Waiting for library publishing...")
    for i in range(20):
        time.sleep(5)
        r = httpx.get(f"{API_BASE}/api/jobs/{job_id}", timeout=10)
        job = r.json()
        print(f"  [{i*5}s] Status: {job['status']}")

        if job["status"] == "PUBLISHED":
            print(f"  Published! Metadata CID: {job['published_cid']}")
            break
    else:
        print("  Timeout waiting for publishing")

    # 8. Check library
    step("8. Checking knowledge library")
    r = httpx.get(f"{API_BASE}/api/library", timeout=10)
    library = r.json()
    print(f"  Library version: {library['version']}")
    print(f"  Total entries: {library['total_entries']}")
    if library.get("index_cid"):
        print(f"  Index CID: {library['index_cid']}")
    if library.get("ipns_name"):
        print(f"  IPNS name: {library['ipns_name']}")

    entries = library.get("entries", {})
    if isinstance(entries, dict):
        entries = entries.values()

    for entry in entries:
        print(f"\n  Entry: {entry['title']}")
        print(f"    CID: {entry['cid']}")
        print(f"    Summary: {entry['summary'][:100]}...")

    step("DONE - Workflow complete!")


if __name__ == "__main__":
    main()
