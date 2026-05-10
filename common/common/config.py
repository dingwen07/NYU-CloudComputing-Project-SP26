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
    # Public IPFS gateway for content reads (fallback when no local node)
    IPFS_GATEWAY_URL: str = "https://ipfs.io/ipfs/"

    # App
    IPNS_LIBRARY_NAME: str = "knowledge-library"
    POLL_INTERVAL_SECONDS: int = 10

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
