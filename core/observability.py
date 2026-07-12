import os
from dotenv import load_dotenv
from langfuse.langchain import CallbackHandler
import structlog

# Load .env file explicitly
load_dotenv()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()

def get_langfuse_handler() -> CallbackHandler | None:
    """Initialize Langfuse callback handler if credentials are available"""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        logger.warning("Langfuse keys not found. Observability disabled.")
        return None

    try:
        handler = CallbackHandler(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        logger.info("Langfuse observability enabled")
        return handler
    except Exception as e:
        logger.error("Failed to initialize Langfuse", error=str(e))
        return None


def get_logger():
    """Return structured logger"""
    return logger