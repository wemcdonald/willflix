"""Vendor-neutral LLM wrapper. Claude Haiku by default, swappable via config."""

import json
import logging
from typing import Optional

from . import config

log = logging.getLogger(__name__)

# Provider implementations. Each takes (model, system, prompt, api_key) and returns str.
_PROVIDERS = {}


def _register(name):
    def decorator(fn):
        _PROVIDERS[name] = fn
        return fn
    return decorator


@_register("anthropic")
def _anthropic(model: str, system: Optional[str], prompt: str, api_key: str) -> str:
    import urllib.request

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"]


@_register("openai")
def _openai(model: str, system: Optional[str], prompt: str, api_key: str) -> str:
    import urllib.request

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = {"model": model, "max_tokens": 1024, "messages": messages}

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


@_register("gemini")
def _gemini(model: str, system: Optional[str], prompt: str, api_key: str) -> str:
    import urllib.request

    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    body = {"contents": [{"parts": [{"text": full_prompt}]}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


# Default models per provider
_DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}

# Secret file names per provider
_SECRET_NAMES = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
}


def ask(prompt: str, system: Optional[str] = None) -> Optional[str]:
    """Send a prompt to the configured LLM. Returns response text or None on failure."""
    cfg = config.load_config()
    provider = cfg.get("LLM_PROVIDER", "anthropic")
    model = cfg.get("LLM_MODEL", _DEFAULT_MODELS.get(provider, ""))

    if provider not in _PROVIDERS:
        log.error(f"Unknown LLM provider: {provider}")
        return None

    try:
        api_key = config.read_secret(_SECRET_NAMES[provider])
    except (FileNotFoundError, KeyError):
        log.error(f"API key not found for provider: {provider}")
        return None

    try:
        return _PROVIDERS[provider](model, system, prompt, api_key)
    except Exception as e:
        log.warning(f"LLM call failed ({provider}/{model}): {e}")
        return None
