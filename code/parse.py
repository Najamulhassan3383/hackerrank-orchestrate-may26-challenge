"""Turn the model's text into the five answer fields."""

import json
import re

ANSWER_FIELDS = (
    "status",
    "product_area",
    "response",
    "justification",
    "request_type",
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_answer(raw: str) -> dict[str, str]:
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON value is not an object")

    return {key: "" if data.get(key) is None else str(data.get(key, "")) for key in ANSWER_FIELDS}
