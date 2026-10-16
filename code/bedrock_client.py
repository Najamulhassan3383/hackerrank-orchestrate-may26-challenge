"""One Amazon Bedrock Converse call. Returns the model text unchanged."""

import os

import boto3

REQUIRED_ENV = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "BEDROCK_MODEL",
)


def missing_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def complete(system_text: str, user_text: str) -> str:
    missing = missing_env()
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"Missing environment variables: {names}")

    client = boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])
    response = client.converse(
        modelId=os.environ["BEDROCK_MODEL"],
        system=[{"text": system_text}],
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        inferenceConfig={"temperature": 0},
    )
    parts = response["output"]["message"]["content"]
    return "".join(part["text"] for part in parts if "text" in part)
