from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

from aida.logging_utils import get_logger
from aida.brain.system_prompt import AIDA_SYSTEM_PROMPT

log = get_logger(__name__)


class AIDABrain:
    def __init__(self) -> None:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not set")
        if not api_key:
            raise RuntimeError("AZURE_OPENAI_API_KEY is not set")
        if not deployment:
            raise RuntimeError("AZURE_OPENAI_DEPLOYMENT is not set")

        self.deployment = deployment
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
        )

    def think(self, user_input: str, context: Optional[List[str]] = None) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": AIDA_SYSTEM_PROMPT}
        ]

        if context:
            messages.append(
                {
                    "role": "system",
                    "content": "Context:\n" + "\n".join(context),
                }
            )

        messages.append({"role": "user", "content": user_input})

        log.info("Sending reasoning request to AIDA brain")

        last_exc: Optional[Exception] = None

        for attempt in range(1, 4):
            try:
                resp = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.2,
                    max_completion_tokens=500,
                )

                content = resp.choices[0].message.content or ""
                content = content.strip()
                if not content:
                    raise RuntimeError("Empty response from AIDA brain")

                return content

            except Exception as exc:
                last_exc = exc
                log.warning("AIDA brain attempt %d failed: %s", attempt, exc)
                time.sleep(0.8 * attempt)

        raise RuntimeError(f"AIDA brain failed after retries: {last_exc}")
