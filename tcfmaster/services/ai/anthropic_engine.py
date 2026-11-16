"""Moteur en ligne : Claude, via le SDK officiel `anthropic`.

La clé API est lue dans le coffre d'identifiants du système (jamais dans le
code ni dans la base). Toute erreur est convertie en `AIUnavailable` : le
service bascule alors sur le tuteur local.

Les replis côté serveur (« server-side fallback ») sont activés : si le
modèle demandé décline une requête, l'API réessaie avec un modèle de
substitution. Un refus final est signalé proprement à l'apprenant.
"""
from __future__ import annotations

import logging

from tcfmaster.services.ai import prompts as P
from tcfmaster.services.ai.base import (OPENING_CUES, AIUnavailable, Conversation, TutorReply,
                                        build_messages)

log = logging.getLogger("tcfmaster.ai")

DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000
MAX_HISTORY_TURNS = 40
REFUSAL_TEXT = ("Je ne peux pas répondre à cette demande. Reformulez votre message ou "
                "revenons à la préparation du TCF IRN.")


class AnthropicEngine:
    name = "Claude (en ligne)"

    def __init__(self, api_key: str | None, model: str = DEFAULT_MODEL,
                 effort: str = "medium", client=None, timeout: float = 120.0):
        if client is None:
            if not api_key:
                raise AIUnavailable("Aucune clé API enregistrée pour Claude.")
            try:
                import anthropic
            except ImportError as exc:
                raise AIUnavailable("La bibliothèque « anthropic » n'est pas installée.") \
                    from exc
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.client = client
        self.model = model or DEFAULT_MODEL
        self.effort = effort if effort in EFFORTS else "medium"

    # ------------------------------------------------------------- appel
    def _messages(self, conv: Conversation, extra_user: str | None = None) -> list[dict]:
        return build_messages(conv, extra_user, MAX_HISTORY_TURNS)

    def _call(self, system: str, messages: list[dict]) -> str:
        import anthropic
        try:
            resp = self.client.beta.messages.create(
                model=self.model, max_tokens=MAX_TOKENS, system=system, messages=messages,
                thinking={"type": "adaptive"}, output_config={"effort": self.effort},
                betas=[FALLBACK_BETA], fallbacks="default")
        except anthropic.AuthenticationError as exc:
            raise AIUnavailable("Clé API refusée : vérifiez-la dans les Paramètres.") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIUnavailable("Cette clé API n'a pas accès au modèle demandé.") from exc
        except anthropic.RateLimitError as exc:
            raise AIUnavailable("Limite d'utilisation atteinte : réessayez plus tard.") from exc
        except anthropic.BadRequestError as exc:
            log.warning("Requête refusée par l'API : %s", exc)
            raise AIUnavailable("Requête refusée par le service en ligne.") from exc
        except anthropic.APIStatusError as exc:
            raise AIUnavailable(f"Service en ligne indisponible (erreur {exc.status_code}).") \
                from exc
        except anthropic.APIConnectionError as exc:
            raise AIUnavailable("Pas de connexion au service en ligne.") from exc
        if resp.stop_reason == "refusal":
            return REFUSAL_TEXT
        text = "".join(getattr(b, "text", "") for b in resp.content
                       if getattr(b, "type", "") == "text").strip()
        if not text:
            raise AIUnavailable("Réponse vide du service en ligne.")
        return text

    # ------------------------------------------------------------- API du moteur
    def opening(self, conv: Conversation) -> TutorReply:
        cue = OPENING_CUES[conv.mode]
        return TutorReply(self._call(P.system_prompt(conv), self._messages(conv, cue)),
                          self.name)

    def reply(self, conv: Conversation, text: str) -> TutorReply:
        return TutorReply(self._call(P.system_prompt(conv), self._messages(conv)), self.name)

    def feedback(self, conv: Conversation, evaluation: dict) -> str:
        summary = (f"Note estimée par l'application : {evaluation['note20']:.1f}/20 "
                   f"(niveau estimé {evaluation['level']}). {P.FEEDBACK}")
        return self._call(P.system_prompt(conv), self._messages(conv, summary))

    def ping(self) -> str:
        return self._call(P.COMMON, [{"role": "user",
                                      "content": "Réponds seulement : « Connexion réussie. »"}])

    def deepen(self, kind: str, data: dict) -> str:
        """Correction approfondie d'une production écrite (EE) ou orale (EO)."""
        return self._call(P.DEEPEN_SYSTEM, [{"role": "user",
                                             "content": P.deepen_request(kind, data)}])
