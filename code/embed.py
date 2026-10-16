"""Turn one piece of text into a 1024-number vector with Bedrock Titan."""

import json
import os
import threading
import time

import boto3
from botocore.exceptions import ClientError

DIMENSIONS = 1024
_RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}

_client = None
_lock = threading.Lock()


def _runtime():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])
    return _client


def embed_text(text: str) -> list[float]:
    model_id = os.environ.get("BEDROCK_EMBEDDING_MODEL")
    if not model_id:
        raise RuntimeError("Missing environment variable: BEDROCK_EMBEDDING_MODEL")
    if not os.environ.get("AWS_REGION"):
        raise RuntimeError("Missing environment variable: AWS_REGION")

    payload = json.dumps(
        {
            "inputText": text,
            "dimensions": DIMENSIONS,
            "normalize": True,
        }
    )
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = _runtime().invoke_model(
                modelId=model_id,
                body=payload,
                contentType="application/json",
                accept="application/json",
            )
            data = json.loads(response["body"].read())
            vector = data["embedding"]
            if len(vector) != DIMENSIONS:
                raise RuntimeError(f"Expected {DIMENSIONS} numbers, got {len(vector)}")
            return vector
        except ClientError as exc:
            last_error = exc
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in _RETRYABLE or attempt == 4:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Embedding failed") from last_error


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"
