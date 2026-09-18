import logging
import sys


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    # Quiet noisy third-party loggers so trading-relevant logs aren't buried.
    # (MetaApi's SDK uses socketio/engineio under the hood for its RPC connection.)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("socketio").setLevel(logging.WARNING)
    logging.getLogger("engineio").setLevel(logging.WARNING)
