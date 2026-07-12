import os
from dotenv import load_dotenv
from langfuse.langchain import CallbackHandler
import structlog

load_dotenv()

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


def get_langfuse_handler() -> CallbackHandler | None:
    """Initialize Langfuse - simplest and most compatible way"""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        logger.warning("Langfuse keys not found. Observability disabled.")
        return None

    try:
        # Clean initialization - no extra arguments
        handler = CallbackHandler()
        logger.info("Langfuse observability enabled")
        return handler
    except Exception as e:
        logger.error("Failed to initialize Langfuse", error=str(e))
        return None


def get_langfuse_client():
    """Return Langfuse client for adding metadata/tags"""
    try:
        from langfuse import Langfuse
        return Langfuse()
    except Exception:
        return None


def get_logger():
    return logger