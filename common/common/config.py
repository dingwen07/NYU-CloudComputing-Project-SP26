from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # GCP / Firestore
    GCP_PROJECT_ID: str = "ian-knowledge-mgmt"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-5.4-mini"
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"

    # IPFS (Kubo RPC — can be empty if service only uses gateway reads)
    IPFS_API_URL: str = "http://localhost:5001/api/v0"
    IPFS_CLI_API: str = ""
    # Public IPFS gateway for content reads (fallback when no local node)
    IPFS_GATEWAY_URL: str = "https://ipfs.io/ipfs/"

    # App
    IPNS_LIBRARY_NAME: str = "knowledge-library"
    IPNS_PUBLISH_REPETITIONS: int = 1
    IPNS_PUBLISH_TIME_SEQUENCE: bool = False
    IPNS_PUBLISH_LIFETIME: str = "8760h"
    POLL_INTERVAL_SECONDS: int = 10

    # libp2p service mesh
    P2P_ENABLED: bool = True
    P2P_NODE_ID: str = ""
    P2P_PORT: int = 9000
    P2P_ADVERTISE_HOST: str = ""
    P2P_ADVERTISE_ADDRS: str = ""
    P2P_AUTO_ADVERTISE_PUBLIC_IP: bool = True
    P2P_REGISTER_ENABLED: bool = True
    P2P_DIAL_TIMEOUT_SECONDS: int = 5
    P2P_DISCOVERY_INTERVAL_SECONDS: int = 10
    P2P_NODE_TTL_SECONDS: int = 120

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
