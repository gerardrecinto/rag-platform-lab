import os


def env(name, default=None):
    return os.environ.get(name, default)


DATABASE_URL = env("DATABASE_URL", "postgresql://rag:rag@localhost:5432/rag")
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
NEO4J_URI = env("NEO4J_URI")  # unset disables graph retrieval
NEO4J_AUTH = (env("NEO4J_USER", "neo4j"), env("NEO4J_PASSWORD", "lab-password"))
API_TOKEN = env("API_TOKEN", "lab-token")
PROVIDER = env("LLM_PROVIDER", "mock")  # mock, anthropic, openai, bedrock
EMBED_DIM = 256
TOP_K = int(env("TOP_K", "4"))
