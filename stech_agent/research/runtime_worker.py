from __future__ import annotations

from stech_agent.research.edge_chatgpt import EdgeChatGPTWorker


class RuntimeEdgeChatGPTWorker(EdgeChatGPTWorker):
    """Production Edge worker with environment preflight.

    The V7.2 browser implementation is intentionally left intact.  The live
    agent checks that Selenium can be imported before discovering or launching
    Edge, so a stale virtualenv cannot open a browser and then fail immediately.
    """

    def start(self) -> None:
        if self.is_alive():
            return
        # Fail before touching Edge/ports when the local virtualenv is stale.
        self._selenium()
        super().start()
