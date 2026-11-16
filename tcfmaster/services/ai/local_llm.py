"""IA locale gratuite : Ollama ou LM Studio, via leur API compatible OpenAI.

Aucune clé ni abonnement : le modèle tourne sur l'ordinateur du candidat
(Ollama : http://localhost:11434/v1 ; LM Studio : http://localhost:1234/v1).
Les requêtes vers l'adresse locale contournent tout proxy système, et rien
n'est envoyé sur Internet tant que l'adresse reste locale.

Toute erreur (serveur arrêté, modèle absent, délai dépassé) devient une
`AIUnavailable` : le service bascule alors sur le tuteur hors ligne intégré.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from tcfmaster.services.ai import prompts as P
from tcfmaster.services.ai.base import (OPENING_CUES, AIUnavailable, Conversation, TutorReply,
                                        build_messages)

log = logging.getLogger("tcfmaster.ai")

PRESETS = {
    "ollama": ("Ollama", "http://localhost:11434/v1"),
    "lmstudio": ("LM Studio", "http://localhost:1234/v1"),
}
DEFAULT_URL = PRESETS["ollama"][1]
MAX_HISTORY_TURNS = 30
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def normalize_url(url: str) -> str:
    """« localhost:11434 » → « http://localhost:11434/v1 » ; refuse les adresses invalides."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_URL
    if "://" not in url:
        url = "http://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise AIUnavailable(f"Adresse du serveur d'IA locale invalide : {url}")
    if not p.path or p.path == "/":
        url += "/v1"
    return url


def is_local(url: str) -> bool:
    """Vrai si l'adresse désigne cet ordinateur ou le réseau local (rien ne sort sur Internet)."""
    try:
        host = urlparse(normalize_url(url)).hostname or ""
    except AIUnavailable:
        return False
    if host in ("localhost",) or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class LocalLLMEngine:
    """Moteur conversationnel pour tout serveur compatible OpenAI (Ollama, LM Studio…)."""

    def __init__(self, base_url: str = DEFAULT_URL, model: str = "", timeout: float = 180.0,
                 opener=None):
        self.base_url = normalize_url(base_url)
        self.model = (model or "").strip()
        self.timeout = timeout
        if opener is None:
            # Pas de proxy pour une adresse locale (sinon la requête partirait vers le proxy).
            handlers = [urllib.request.ProxyHandler({})] if is_local(self.base_url) else []
            opener = urllib.request.build_opener(*handlers)
        self.opener = opener

    @property
    def name(self) -> str:
        return f"IA locale ({self.model or 'modèle par défaut'})"

    # ------------------------------------------------------------- HTTP
    def _request(self, path: str, payload: dict | None = None) -> dict:
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # pragma: no cover
                pass
            if exc.code == 404:
                raise AIUnavailable(
                    f"Modèle « {self.model or '?'} » introuvable sur le serveur d'IA locale. "
                    "Téléchargez-le (par exemple : ollama pull mistral) ou choisissez un "
                    "modèle de la liste.") from exc
            log.warning("IA locale : erreur HTTP %s %s", exc.code, detail)
            raise AIUnavailable(f"Le serveur d'IA locale a répondu par une erreur "
                                f"({exc.code}).") from exc
        except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError) as exc:
            raise AIUnavailable(
                f"Serveur d'IA locale injoignable ({self.base_url}). Lancez Ollama ou "
                "LM Studio (serveur local démarré), puis réessayez.") from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise AIUnavailable("Réponse illisible du serveur d'IA locale.") from exc

    def list_models(self) -> list[str]:
        data = self._request("/models")
        models = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
        return sorted(m for m in models if m)

    def _model(self) -> str:
        if not self.model:
            models = self.list_models()
            if not models:
                raise AIUnavailable("Aucun modèle installé sur le serveur d'IA locale "
                                    "(exemple : ollama pull mistral).")
            self.model = models[0]
        return self.model

    def _call(self, system: str, messages: list[dict]) -> str:
        payload = {"model": self._model(), "stream": False, "temperature": 0.4,
                   "messages": [{"role": "system", "content": system}] + messages}
        data = self._request("/chat/completions", payload)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable("Réponse inattendue du serveur d'IA locale.") from exc
        text = _THINK.sub("", text).strip()        # modèles « à raisonnement » (Qwen, DeepSeek…)
        if not text:
            raise AIUnavailable("Réponse vide du serveur d'IA locale.")
        return text

    # ------------------------------------------------------------- API du moteur
    def _messages(self, conv: Conversation, extra: str | None = None) -> list[dict]:
        return build_messages(conv, extra, MAX_HISTORY_TURNS)

    def opening(self, conv: Conversation) -> TutorReply:
        return TutorReply(self._call(P.system_prompt(conv),
                                     self._messages(conv, OPENING_CUES[conv.mode])), self.name)

    def reply(self, conv: Conversation, text: str) -> TutorReply:
        return TutorReply(self._call(P.system_prompt(conv), self._messages(conv)), self.name)

    def feedback(self, conv: Conversation, evaluation: dict) -> str:
        summary = (f"Note estimée par l'application : {evaluation['note20']:.1f}/20 "
                   f"(niveau estimé {evaluation['level']}). {P.FEEDBACK}")
        return self._call(P.system_prompt(conv), self._messages(conv, summary))

    def deepen(self, kind: str, data: dict) -> str:
        return self._call(P.DEEPEN_SYSTEM, [{"role": "user",
                                             "content": P.deepen_request(kind, data)}])

    def ping(self) -> str:
        models = self.list_models()
        model = self._model()
        if models and model not in models:
            raise AIUnavailable(f"Modèle « {model} » absent du serveur. Modèles disponibles : "
                                + ", ".join(models[:10]))
        answer = self._call(P.COMMON, [{"role": "user",
                                        "content": "Réponds seulement : « Connexion réussie. »"}])
        return f"IA locale joignable · modèle {model}\nRéponse : {answer[:200]}"
