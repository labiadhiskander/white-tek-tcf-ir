"""Service du tuteur IA : choix du moteur, conversation, repli hors ligne, évaluation."""
from __future__ import annotations

import logging
import random

from sqlalchemy import select

from tcfmaster.core import levels as L
from tcfmaster.db.models import SpeakingTask
from tcfmaster.services import error_tracking as ET
from tcfmaster.services import settings as S
from tcfmaster.services.ai.anthropic_engine import DEFAULT_MODEL, AnthropicEngine
from tcfmaster.services.ai.base import (LEARNER, MODE_EXAMINER, MODES, TUTOR, AIUnavailable,
                                        Conversation, TutorReply, Turn)
from tcfmaster.services.ai.local import LocalTutor, evaluate_exam
from tcfmaster.services.ai.local_llm import DEFAULT_URL, LocalLLMEngine, is_local

log = logging.getLogger("tcfmaster.ai")

PROVIDER_LOCAL, PROVIDER_ANTHROPIC, PROVIDER_LOCAL_LLM = "local", "anthropic", "local_llm"
PROVIDERS = {PROVIDER_LOCAL: "Tuteur hors ligne (intégré, gratuit)",
             PROVIDER_LOCAL_LLM: "IA locale gratuite (Ollama ou LM Studio, sur votre ordinateur)",
             PROVIDER_ANTHROPIC: "Claude (Anthropic, en ligne, clé API personnelle, facultatif)"}
PRIVACY_NOTICE = ("Avec Claude (en ligne), vos messages sont envoyés à Anthropic pour "
                  "générer les réponses. N'y écrivez pas d'informations personnelles "
                  "sensibles. Le tuteur hors ligne et l'IA locale (Ollama, LM Studio), eux, "
                  "ne transmettent rien sur Internet.")
DEEPEN_KINDS = ("EE", "EO")


def task_dict(t: SpeakingTask) -> dict:
    return {"id": t.id, "task_number": t.task_number, "title": t.title, "scenario": t.scenario,
            "examiner_role": t.examiner_role, "duration_s": t.duration_s,
            "examiner_prompts": list(t.examiner_prompts or []),
            "useful_phrases": list(t.useful_phrases or []), "model_answer": t.model_answer,
            "exam_code": t.exam.code if t.exam else ""}


class TutorService:
    def __init__(self, db, online_factory=None, rng: random.Random | None = None,
                 local_llm_factory=None):
        """`online_factory(api_key, model, effort)` : fabrique du moteur en ligne ;
        `local_llm_factory(url, model)` : fabrique de l'IA locale (remplacées dans les
        tests)."""
        self.db = db
        self.rng = rng or random.Random()
        self.local = LocalTutor(db, self.rng)
        self.online_factory = online_factory or (
            lambda key, model, effort: AnthropicEngine(key, model, effort))
        self.local_llm_factory = local_llm_factory or (
            lambda url, model: LocalLLMEngine(url, model))
        self._online = None
        self._online_sig = None

    # ------------------------------------------------------------ moteurs
    def provider(self) -> str:
        with self.db.session() as s:
            p = S.get(s, "ai_provider") or PROVIDER_LOCAL
        return p if p in PROVIDERS else PROVIDER_LOCAL

    def online_engine(self):
        """Moteur avancé configuré (Claude ou IA locale), ou None (tuteur hors ligne,
        clé absente…). Le tuteur hors ligne reste le repli en cas d'échec."""
        provider = self.provider()
        if provider == PROVIDER_LOCAL:
            return None
        with self.db.session() as s:
            st = S.all_settings(s)
        if provider == PROVIDER_LOCAL_LLM:
            url, model = st.get("local_ai_url") or DEFAULT_URL, st.get("local_ai_model") or ""
            sig = (provider, url, model)
            factory = lambda: self.local_llm_factory(url, model)  # noqa: E731
        else:
            model = st.get("ai_model") or DEFAULT_MODEL
            effort = st.get("ai_effort") or "medium"
            key = S.load_api_key(PROVIDER_ANTHROPIC)
            sig = (provider, bool(key), hash(key), model, effort)
            factory = lambda: self.online_factory(key, model, effort)  # noqa: E731
        if self._online is None or sig != self._online_sig:
            try:
                self._online = factory()
            except AIUnavailable as exc:
                log.info("Moteur avancé indisponible : %s", exc)
                self._online = None
            self._online_sig = sig
        return self._online

    def status(self) -> str:
        provider = self.provider()
        if provider == PROVIDER_ANTHROPIC:
            if self.online_engine() is not None:
                with self.db.session() as s:
                    model = S.get(s, "ai_model") or DEFAULT_MODEL
                return f"Claude (en ligne, modèle {model}) · repli hors ligne automatique"
            return ("Claude choisi mais aucune clé API enregistrée : tuteur hors ligne "
                    "utilisé (voir Paramètres)")
        if provider == PROVIDER_LOCAL_LLM:
            if self.online_engine() is None:
                return "IA locale mal configurée : tuteur hors ligne utilisé (voir Paramètres)"
            with self.db.session() as s:
                url = S.get(s, "local_ai_url") or DEFAULT_URL
                model = S.get(s, "local_ai_model") or "modèle par défaut"
            where = "sur votre ordinateur" if is_local(url) else f"serveur {url}"
            return f"IA locale ({model}, {where}) · repli hors ligne automatique"
        return "Tuteur hors ligne (aucune donnée n'est envoyée sur Internet)"

    def needs_consent(self) -> bool:
        """Consentement requis seulement si des messages quittent l'ordinateur ou le
        réseau local (Claude, ou IA « locale » configurée sur une adresse distante)."""
        if self.online_engine() is None:
            return False
        if self.provider() == PROVIDER_LOCAL_LLM:
            with self.db.session() as s:
                if is_local(S.get(s, "local_ai_url") or DEFAULT_URL):
                    return False
        with self.db.session() as s:
            return not S.get(s, "ai_consent")

    def give_consent(self) -> None:
        with self.db.session() as s:
            S.set_(s, "ai_consent", True)

    def _run(self, call_online, call_local) -> TutorReply:
        engine = self.online_engine()
        if engine is not None and not self.needs_consent():
            try:
                return call_online(engine)
            except AIUnavailable as exc:
                log.warning("Repli sur le tuteur hors ligne : %s", exc)
                r = call_local()
                r.notice = f"{exc} Réponse du tuteur hors ligne."
                return r
        return call_local()

    # ------------------------------------------------------------ conversation
    def new_conversation(self, mode: str, task_number: int | None = None,
                         task_id: int | None = None) -> Conversation:
        if mode not in MODES:
            raise ValueError(f"Mode inconnu : {mode}")
        with self.db.session() as s:
            profile = ET.recent_summary(s)
            task = None
            if mode == MODE_EXAMINER:
                t = s.get(SpeakingTask, task_id) if task_id else None
                if t is None:
                    q = select(SpeakingTask)
                    if task_number:
                        q = q.where(SpeakingTask.task_number == task_number)
                    tasks = list(s.execute(q).scalars())
                    if not tasks:
                        raise RuntimeError("Aucun sujet d'expression orale disponible.")
                    t = self.rng.choice(tasks)
                task = task_dict(t)
        return Conversation(mode=mode, task=task, learner_profile=profile)

    def opening(self, conv: Conversation) -> TutorReply:
        r = self._run(lambda e: e.opening(conv), lambda: self.local.opening(conv))
        conv.turns.append(Turn(TUTOR, r.text))
        return r

    def send(self, conv: Conversation, text: str) -> TutorReply:
        text = (text or "").strip()
        if not text:
            raise ValueError("Message vide")
        conv.turns.append(Turn(LEARNER, text))
        local_reply = None

        def local():
            nonlocal local_reply
            if local_reply is None:
                local_reply = self.local.reply(conv, text)
            return local_reply

        r = self._run(lambda e: e.reply(conv, text), local)
        conv.turns.append(Turn(TUTOR, r.text))
        # Journal des erreurs : uniquement les règles locales (fiables et explicables).
        if conv.mode != MODE_EXAMINER:
            corrections = local_reply.corrections if local_reply else self._detect(conv, text)
            if corrections:
                with self.db.session() as s:
                    ET.log_issues(s, "IA", corrections)
            r.corrections = r.corrections or corrections
        return r

    @staticmethod
    def _detect(conv: Conversation, text: str) -> list[dict]:
        from tcfmaster.services import speaking_eval as SE
        from tcfmaster.services import writing_eval as WE
        from tcfmaster.services.writing_rules import ERROR
        issues = WE.find_issues(text) if conv.mode != "conversation" else SE.oral_issues(text)
        return [i.__dict__ for i in issues if i.severity == ERROR]

    def finish_exam(self, conv: Conversation) -> TutorReply:
        """Fin de simulation : note estimée (moteur local) + retour qualitatif."""
        if conv.mode != MODE_EXAMINER:
            raise ValueError("Seul le mode examinateur se termine par une évaluation.")
        ev = evaluate_exam(conv)
        with self.db.session() as s:
            ET.log_issues(s, "EO", ev.get("issues") or [])
        text = (f"Note estimée : {ev['note20']:.1f} / 20 · niveau estimé {ev['level']}.\n"
                f"{L.DISCLAIMER}")

        def online(engine):
            fb = engine.feedback(conv, ev)
            return TutorReply(f"{text}\n\n{fb}", engine.name, evaluation=ev)

        def local():
            lines = [text]
            if ev.get("strengths"):
                lines.append("Points forts : " + " ; ".join(ev["strengths"]))
            if ev.get("priorities"):
                lines.append("Priorités : " + " ; ".join(ev["priorities"]))
            return TutorReply("\n\n".join(lines), self.local.name, evaluation=ev)

        r = self._run(online, local)
        if L.DISCLAIMER not in r.text:
            r.text += f"\n\n{L.DISCLAIMER}"
        conv.turns.append(Turn(TUTOR, r.text))
        conv.state["ended"] = True
        return r

    def test_connection(self) -> str:
        engine = self.online_engine()
        if engine is None:
            raise AIUnavailable("Aucune clé API enregistrée, ou fournisseur hors ligne choisi.")
        return engine.ping()

    def list_local_models(self, url: str | None = None) -> list[str]:
        """Modèles installés sur le serveur d'IA locale (Ollama, LM Studio)."""
        if url is None:
            with self.db.session() as s:
                url = S.get(s, "local_ai_url") or DEFAULT_URL
        return self.local_llm_factory(url, "").list_models()

    # ------------------------------------------------ correction approfondie
    def can_deepen(self) -> bool:
        return self.online_engine() is not None and not self.needs_consent()

    def deepen(self, kind: str, submission_id: int) -> str:
        """Approfondit la correction d'une production EE ou EO avec le moteur avancé.

        La note reste celle du barème local (estimation) ; le texte renvoyé se termine
        toujours par la mention « estimation pédagogique ». Lève `AIUnavailable` si
        aucun moteur avancé n'est disponible."""
        from tcfmaster.db.models import SpeakingSubmission, WritingSubmission
        if kind not in DEEPEN_KINDS:
            raise ValueError(f"Épreuve inconnue : {kind}")
        engine = self.online_engine()
        if engine is None:
            raise AIUnavailable("Aucune IA configurée : choisissez l'IA locale (Ollama, "
                                "LM Studio) ou Claude dans les Paramètres.")
        if self.needs_consent():
            raise AIUnavailable("Acceptez d'abord l'avertissement de confidentialité (page "
                                "« Conversation avec l'IA »).")
        with self.db.session() as s:
            model = WritingSubmission if kind == "EE" else SpeakingSubmission
            sub = s.get(model, submission_id)
            if sub is None:
                raise KeyError(f"Production {submission_id} introuvable")
            ev = dict(sub.evaluation or {})
            t = sub.task
            data = {"task_number": t.task_number if t else None,
                    "instructions": (t.instructions if kind == "EE" else
                                     f"{t.title}. {t.scenario}") if t else "",
                    "min_words": getattr(t, "min_words", None),
                    "max_words": getattr(t, "max_words", None),
                    "word_count": getattr(sub, "word_count", None),
                    "text": sub.text if kind == "EE" else sub.transcript,
                    "note20": sub.note20, "level": sub.level,
                    "issues": ev.get("issues") or [], "priorities": ev.get("priorities") or []}
        if not (data["text"] or "").strip():
            raise ValueError("Production vide : rien à approfondir.")
        text = engine.deepen(kind, data)
        if L.DISCLAIMER not in text:
            text += f"\n\n{L.DISCLAIMER}"
        return text
