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

log = logging.getLogger("tcfmaster.ai")

PROVIDER_LOCAL, PROVIDER_ANTHROPIC = "local", "anthropic"
PROVIDERS = {PROVIDER_LOCAL: "Tuteur hors ligne (intégré, gratuit)",
             PROVIDER_ANTHROPIC: "Claude (Anthropic, en ligne, clé API personnelle)"}
PRIVACY_NOTICE = ("Avec Claude (en ligne), vos messages sont envoyés à Anthropic pour "
                  "générer les réponses. N'y écrivez pas d'informations personnelles "
                  "sensibles. Le tuteur hors ligne, lui, ne transmet rien.")


def task_dict(t: SpeakingTask) -> dict:
    return {"id": t.id, "task_number": t.task_number, "title": t.title, "scenario": t.scenario,
            "examiner_role": t.examiner_role, "duration_s": t.duration_s,
            "examiner_prompts": list(t.examiner_prompts or []),
            "useful_phrases": list(t.useful_phrases or []), "model_answer": t.model_answer,
            "exam_code": t.exam.code if t.exam else ""}


class TutorService:
    def __init__(self, db, online_factory=None, rng: random.Random | None = None):
        """`online_factory(api_key, model, effort)` : fabrique du moteur en ligne
        (remplacée dans les tests)."""
        self.db = db
        self.rng = rng or random.Random()
        self.local = LocalTutor(db, self.rng)
        self.online_factory = online_factory or (
            lambda key, model, effort: AnthropicEngine(key, model, effort))
        self._online = None
        self._online_sig = None

    # ------------------------------------------------------------ moteurs
    def provider(self) -> str:
        with self.db.session() as s:
            p = S.get(s, "ai_provider") or PROVIDER_LOCAL
        return p if p in PROVIDERS else PROVIDER_LOCAL

    def online_engine(self):
        """Moteur en ligne configuré, ou None (fournisseur local, clé absente…)."""
        if self.provider() != PROVIDER_ANTHROPIC:
            return None
        with self.db.session() as s:
            model = S.get(s, "ai_model") or DEFAULT_MODEL
            effort = S.get(s, "ai_effort") or "medium"
        key = S.load_api_key(PROVIDER_ANTHROPIC)
        sig = (bool(key), hash(key), model, effort)
        if self._online is None or sig != self._online_sig:
            try:
                self._online = self.online_factory(key, model, effort)
            except AIUnavailable as exc:
                log.info("Moteur en ligne indisponible : %s", exc)
                self._online = None
            self._online_sig = sig
        return self._online

    def status(self) -> str:
        if self.provider() == PROVIDER_ANTHROPIC:
            if self.online_engine() is not None:
                with self.db.session() as s:
                    model = S.get(s, "ai_model") or DEFAULT_MODEL
                return f"Claude (en ligne, modèle {model}) · repli hors ligne automatique"
            return ("Claude choisi mais aucune clé API enregistrée : tuteur hors ligne "
                    "utilisé (voir Paramètres)")
        return "Tuteur hors ligne (aucune donnée n'est envoyée sur Internet)"

    def needs_consent(self) -> bool:
        if self.online_engine() is None:
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
