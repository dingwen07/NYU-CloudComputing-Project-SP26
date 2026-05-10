# NYU Cloud Computing Project SP26

Cloud-based Intelligent Autonomous Networked (IAN) knowledge management framework over a decentralized P2P/IPFS infrastructure.

The application lets users submit IPFS CIDs, routes jobs across a multi-cloud service mesh, analyzes documents with Azure OpenAI, supports human approval, and publishes an updated searchable knowledge library to IPFS with a mutable IPNS pointer.

## Current Stack

| Layer | Technology | Role |
|---|---|---|
| User/API | GCP App Engine Flex | Dashboard, CID submission, review UI, library API |
| Shared state | Firebase/Firestore | Durable jobs, library state, IPNS key storage, peer registry |
| P2P service mesh | libp2p | Node-to-node job event communication |
| AI worker | Azure Container Instances + Azure OpenAI | IPFS fetch, PDF/text analysis, metadata generation |
| Orchestration | AWS ECS Fargate | Job assignment and state transitions |
| Publishing | AWS ECS Fargate + Kubo IPFS | IPFS pinning and IPNS library publishing |
| Local test | Docker Compose | Full-stack local integration testing |

Kubo is used only as the IPFS/IPNS content node. Service-to-service P2P communication is handled by libp2p.

## Live Cloud Endpoints

- App: <https://nyu-cloud-computing-project.ue.r.appspot.com>
- Library IPNS API: <https://nyu-cloud-computing-project.ue.r.appspot.com/api/library/ipns>
- Current verified IPNS name: `k51qzi5uqu5dkcgtoq1y84z5kc026xnc3rhuu96ov4d2w2xbt9qgxfo6o6nvot`
- Current verified library CID: `QmbXrPQp7Jcd9f2qpv8Y56T58jbngNM9FnbpzYS8Li9TFF`

When testing local IPFS commands, unset any custom repo path first:

```bash
unset IPFS_PATH
ipfs name resolve --nocache k51qzi5uqu5dkcgtoq1y84z5kc026xnc3rhuu96ov4d2w2xbt9qgxfo6o6nvot
ipfs cat QmbXrPQp7Jcd9f2qpv8Y56T58jbngNM9FnbpzYS8Li9TFF
```

## Local Development

Create `.env` with cloud credentials and Azure OpenAI settings, then run:

```bash
docker compose up --build
```

Local ports:

| Service | URL |
|---|---|
| API server | <http://localhost:8000> |
| Orchestrator | <http://localhost:8001/health> |
| LLM worker | <http://localhost:8002/health> |
| Library worker | <http://localhost:8003/health> |
| Shared IPFS gateway | <http://localhost:8081/ipfs/> |
| Shared IPFS API | <http://localhost:5001/api/v0> |

