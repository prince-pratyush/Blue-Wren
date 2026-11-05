import json
from collections.abc import Mapping, Sequence

OUTPUT_SCHEMA_VERSION = "analysis.v1"
PERIOD_PATTERN = r"^[0-9]{4}-(Q[1-4]|H[12]|FY)$"
BASES = ("reported", "underlying")
MAX_OBSERVATIONS = 50
_FIELDS = ("metric", "value_text", "unit", "period", "basis", "document_version_id", "locator")
_MAX_LENGTHS = {"value_text": 64, "document_version_id": 256, "locator": 512}


class MalformedOutput(ValueError):
    pass


def output_schema_json(*, metrics: Sequence[str], units: Sequence[str]) -> str:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["observations"],
        "properties": {
            "observations": {
                "type": "array",
                "maxItems": MAX_OBSERVATIONS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(_FIELDS),
                    "properties": {
                        "metric": {"enum": list(metrics)},
                        "value_text": {"type": "string", "maxLength": 64},
                        "unit": {"enum": list(units)},
                        "period": {"type": "string", "pattern": PERIOD_PATTERN},
                        "basis": {"enum": list(BASES)},
                        "document_version_id": {"type": "string", "maxLength": 256},
                        "locator": {"type": "string", "maxLength": 512},
                    },
                },
            }
        },
    }
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


def decode_proposals(text: str) -> tuple[Mapping[str, str], ...]:
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise MalformedOutput("output is not valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"observations"}:
        raise MalformedOutput("output must be an object with only an observations array")
    observations = payload["observations"]
    if not isinstance(observations, list) or len(observations) > MAX_OBSERVATIONS:
        raise MalformedOutput("observations must be an array of at most 50 items")
    decoded = []
    for item in observations:
        if not isinstance(item, dict) or set(item) != set(_FIELDS):
            raise MalformedOutput("observation has missing or extra fields")
        for field, value in item.items():
            if not isinstance(value, str):
                raise MalformedOutput(f"{field} must be a string")
            if len(value) > _MAX_LENGTHS.get(field, 128):
                raise MalformedOutput(f"{field} exceeds its maximum length")
        decoded.append(dict(item))
    return tuple(decoded)
