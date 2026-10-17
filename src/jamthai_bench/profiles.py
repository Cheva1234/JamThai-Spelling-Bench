"""Model profiles: everything model-specific about a run, in one hashed, versionable JSON file."""
import json
from pathlib import Path
from .reasoning import PROFILES

REQUIRED = {"name", "model", "thinking", "reasoning_tags", "max_tokens"}
OPTIONAL = {"extra_body", "notes", "open_tag_in_prompt"}
PROTECTED = {"model", "messages", "temperature", "top_p", "seed", "max_tokens", "max_completion_tokens", "stream", "response_format"}


def load_profile(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Profile must be a JSON object")
    if set(data) - REQUIRED - OPTIONAL:
        raise ValueError(f"Unknown profile keys: {sorted(set(data) - REQUIRED - OPTIONAL)}")
    if REQUIRED - set(data):
        raise ValueError(f"Missing profile keys: {sorted(REQUIRED - set(data))}")
    if not all(isinstance(data[k], str) and data[k] for k in ("name", "model")):
        raise ValueError("name and model (the served model name) must be non-empty text")
    if not isinstance(data["thinking"], str) or data["thinking"] not in ("on", "off"):
        raise ValueError("thinking must be 'on' or 'off'")
    if not isinstance(data["reasoning_tags"], str) or data["reasoning_tags"] not in PROFILES:
        raise ValueError(f"reasoning_tags must be one of {sorted(PROFILES)}")
    flag = data.setdefault("open_tag_in_prompt", False)
    if type(flag) is not bool:
        raise ValueError("open_tag_in_prompt must be true or false")
    if flag and data["reasoning_tags"] == "none":
        raise ValueError("open_tag_in_prompt needs a declared reasoning_tags format")
    mt = data["max_tokens"]
    if not isinstance(mt, dict) or set(mt) != {"A", "B", "C"} or not all(type(v) is int and v >= 1 for v in mt.values()):
        raise ValueError("max_tokens needs integer A, B and C >= 1")
    extra = data.setdefault("extra_body", {})
    if not isinstance(extra, dict) or set(extra) & PROTECTED:
        raise ValueError(f"extra_body must be an object and may not set {sorted(PROTECTED)}")
    return data
