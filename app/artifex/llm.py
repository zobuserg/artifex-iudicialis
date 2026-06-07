"""
Llamador de modelos para las estaciones de la fábrica.

Reusa el motor que ya existe en app/core:
  - el constructor de cliente Anthropic de wiki_worker (_get_client)
  - la cadena de modelos de resolución de claude_worker (Opus → Sonnet)

A diferencia de ClaudeWorker (que es un QThread con streaming para la UI),
aquí las estaciones hacen llamadas simples, no-streaming: entra un prompt,
sale texto. El streaming a la UI se maneja después, en la capa del grafo.
"""

from __future__ import annotations

from app.core.claude_worker import resolution_model_candidates
from app.core.wiki_worker import _get_client


def call_model(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    models: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    """Llama a un modelo (no streaming) probando la cadena de respaldo.

    Devuelve (texto, modelo_usado). Lanza RuntimeError si ningún modelo
    de la cadena responde.
    """
    client = _get_client()
    chain = models or resolution_model_candidates()
    errors: list[str] = []
    for model in chain:
        try:
            kwargs: dict = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                kwargs["system"] = system
            resp = client.messages.create(**kwargs, timeout=600)
            text = "".join(
                getattr(block, "text", "") for block in resp.content
            ).strip()
            return text, model
        except Exception as e:  # noqa: BLE001 — acumula y prueba el siguiente
            errors.append(f"{model}: {e}")
            continue
    raise RuntimeError(
        "Ningún modelo de la cadena respondió. Detalle:\n" + "\n".join(errors)
    )
