"""signal_messenger — standalone Signal client for signal-cli-rest-api.

A small, dependency-light wrapper around the REST API exposed by the
`bbernhard/signal-cli-rest-api` Docker image. It is intentionally free of
any application imports so it can be reused in other projects:

    pip install ./libs/signal_messenger
"""

from .base import Message, Messenger
from .signal_rest import SignalRestClient

__all__ = ["Message", "Messenger", "SignalRestClient"]
__version__ = "0.1.0"
