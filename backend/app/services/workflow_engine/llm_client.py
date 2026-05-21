"""Multi-provider LLM + embedding client for the workflow engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    provider: str  # "openai" | "anthropic" | "google"
    model: str
    api_key: str
    embed_model: str = "text-embedding-3-small"
    embed_api_key: str = field(default="")  # falls back to api_key if empty

    def __post_init__(self) -> None:
        if not self.embed_api_key:
            self.embed_api_key = self.api_key


async def call_llm(config: LLMConfig, system: str, user: str, max_tokens: int = 10) -> str:
    """Route a chat completion request to the configured provider."""
    if config.provider == "anthropic":
        return await _call_anthropic(config, system, user, max_tokens)
    if config.provider == "google":
        return await _call_google(config, system, user, max_tokens)
    return await _call_openai(config, system, user, max_tokens)


async def embed_text(config: LLMConfig, text: str) -> list[float]:
    """Return a text embedding vector using OpenAI's embedding API.

    Always uses OpenAI embeddings regardless of LLM provider, since
    text-embedding-3-small is the most cost-effective multilingual option
    and node embeddings are stored in the same space.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.embed_api_key)
    response = await client.embeddings.create(model=config.embed_model, input=text)
    return response.data[0].embedding


async def _call_openai(config: LLMConfig, system: str, user: str, max_tokens: int) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.api_key)
    response = await client.chat.completions.create(
        model=config.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()


async def _call_anthropic(config: LLMConfig, system: str, user: str, max_tokens: int) -> str:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("anthropic SDK not installed — add it to dependencies") from exc

    client = anthropic.AsyncAnthropic(api_key=config.api_key)
    message = await client.messages.create(
        model=config.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    content = message.content
    return str(content[0].text if content else "").strip()


async def _call_google(config: LLMConfig, system: str, user: str, max_tokens: int) -> str:
    try:
        import google.generativeai as genai  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "google-generativeai SDK not installed — add it to dependencies"
        ) from exc

    genai.configure(api_key=config.api_key)
    model = genai.GenerativeModel(config.model, system_instruction=system)
    response = await model.generate_content_async(
        user,
        generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens, temperature=0),
    )
    return str(response.text).strip()
