# SPDX-License-Identifier: Apache-2.0
import json
from typing import Any, Union

from haystack import component, default_from_dict, default_to_dict
from haystack.utils import Secret, deserialize_secrets_inplace

from ._client import arequest, clean, request, resolve_key


@component
class OlostepAnswer:
    """
    Answers a question from the live web with Olostep, and returns the answer with its source URLs.

    Pass `json_format` to get the answer as structured data in that shape.

    Usage:
    ```python
    from haystack_integrations.components.websearch.olostep import OlostepAnswer

    answer = OlostepAnswer(json_format={"company": "", "founded": ""})
    result = answer.run(query="When was deepset founded?")
    result["answer"], result["links"]
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("OLOSTEP_API_KEY"),
        json_format: dict[str, Any] | None = None,
        timeout: float = 180.0,
    ):
        """
        :param api_key: Olostep API key. Defaults to the `OLOSTEP_API_KEY` environment variable.
        :param json_format: Optional shape for a structured answer, such as `{"name": "", "price": ""}`.
        :param timeout: Seconds to wait for the answer.
        """
        self.api_key = api_key
        self.json_format = json_format
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(self, api_key=self.api_key.to_dict(), json_format=self.json_format, timeout=self.timeout)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OlostepAnswer":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    def _payload(self, query: str) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        return clean({"task": query.strip(), "json_format": self.json_format})

    @staticmethod
    def _output(data: dict[str, Any]) -> dict[str, Any]:
        result = data.get("result") or {}
        answer: Any = result.get("json_content")
        if isinstance(answer, str):
            try:
                answer = json.loads(answer)
            except ValueError:
                pass
        return {"answer": answer, "links": list(result.get("sources") or [])}

    @component.output_types(answer=Union[str, dict[str, Any]], links=list[str])
    def run(self, query: str) -> dict[str, Any]:
        """
        Answer the question.

        :param query: The question or research task, in plain language.
        :returns: A dictionary with `answer` (text, or a dictionary when `json_format` is set) and
            `links` (the source URLs).
        """
        return self._output(
            request("POST", "/answers", resolve_key(self.api_key), self.timeout, json=self._payload(query))
        )

    @component.output_types(answer=Union[str, dict[str, Any]], links=list[str])
    async def run_async(self, query: str) -> dict[str, Any]:
        """Async version of :meth:`run`."""
        data = await arequest("POST", "/answers", resolve_key(self.api_key), self.timeout, json=self._payload(query))
        return self._output(data)
