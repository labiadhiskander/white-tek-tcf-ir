"""Tuteur local, hors ligne et toujours disponible.

Il ne « comprend » pas le français comme un grand modèle de langage : il
s'appuie sur les règles de correction de l'application, les cours de
grammaire, le vocabulaire et une banque de sujets. Ses limites sont
annoncées à l'apprenant.
"""
from __future__ import annotations

import random
import re
import unicodedata

from sqlalchemy import func, or_, select

from tcfmaster.db.models import Expression, GrammarChapter, GrammarExercise, VocabWord
from tcfmaster.services import learning as LS
from tcfmaster.services import speaking_eval as SE
from tcfmaster.services import writing_eval as WE
from tcfmaster.services.ai.base import (MODE_CONVERSATION, MODE_EXAMINER, MODE_TEACHER,
                                        Conversation, TutorReply)
from tcfmaster.services.writing_rules import ERROR

LIMITS = ("Je suis le tuteur hors ligne : je repère les erreurs fréquentes grâce à des règles, "
          "mais je ne vois pas tout. Pour une correction plus fine, vous pouvez activer Claude "
          "(en ligne) dans les Paramètres.")

# Mots-clés → chapitre de grammaire (comparaison sans accents).
GRAMMAR_KEYWORDS: dict[str, list[str]] = {
    "subjonctif": ["subjonctif", "il faut que", "que je sois", "bien que"],
    "hypotheses": ["hypothese", "si j'avais", "si + ", "condition"],
    "conditionnel": ["conditionnel"],
    "pronoms-relatifs": ["relatif", "dont", "lequel", "laquelle", "auquel", "duquel"],
    "voix-passive": ["passif", "passive"],
    "discours-indirect": ["discours indirect", "discours rapporte", "style indirect"],
    "pronoms-personnels": ["pronom personnel", "pronoms personnels", "cod", "coi",
                           "pronom y", "pronom en", "le pronom"],
    "passe-compose": ["passe compose", "auxiliaire", "etre ou avoir"],
    "imparfait": ["imparfait"],
    "plus-que-parfait": ["plus-que-parfait", "plus que parfait"],
    "futur-simple": ["futur simple", "futur proche"],
    "futur-anterieur": ["futur anterieur"],
    "prepositions": ["preposition", "a ou de", "en ou au"],
    "articles": ["article", "partitif", "du ou de"],
    "accords": ["accord", "participe passe", "accorder"],
    "adjectifs": ["adjectif"],
    "adverbes": ["adverbe", "-ment"],
    "negation": ["negation", "ne pas", "ne plus", "ne jamais", "ne que"],
    "comparaison": ["comparaison", "comparatif", "superlatif", "plus que", "moins que"],
    "phrases-complexes": ["cause", "consequence", "opposition", "concession", "le but"],
    "concordance-temps": ["concordance"],
    "connecteurs": ["connecteur", "articulateur", "mots de liaison"],
    "present": ["present de l'indicatif", "le present"],
}
_QUESTION = re.compile(r"\?|^(explique|expliquez|c'est quoi|qu'est-ce que|comment|quand|"
                       r"pourquoi|quelle (est la )?difference|peux-tu|pouvez-vous|je ne "
                       r"comprends pas|aide-moi|j'ai du mal)", re.I)
_VOCAB = re.compile(r"(?:que (?:veut dire|signifie)|sens d[eu]|d[ée]finition d[eu]|"
                    r"synonymes? d[eu])\s+(?:l[ae'] ?mot\s+|l'expression\s+)?[«\"']?\s*"
                    r"([^«»\"?]+?)\s*[»\"']?\s*\??\s*$", re.I)
_CHANGE_TOPIC = re.compile(r"\b(autre sujet|changer de sujet|change de sujet|"
                           r"nouveau sujet|on change)\b", re.I)
_OPINION = re.compile(r"\b(je pense|je crois|à mon avis|selon moi|pour ma part|"
                      r"je trouve|personnellement|il me semble)\b", re.I)

TOPICS: list[dict] = [
    {"title": "le logement", "questions": [
        "Parlons du logement. Où habitez-vous et qu'est-ce qui vous plaît dans votre quartier ?",
        "Préférez-vous vivre en ville ou à la campagne ? Pourquoi ?",
        "À votre avis, pourquoi est-il si difficile de se loger dans les grandes villes ?",
        "Que devraient faire les pouvoirs publics pour aider les jeunes à se loger ?",
        "Si vous pouviez changer une chose dans votre logement, ce serait quoi ?"]},
    {"title": "le travail", "questions": [
        "Parlons du travail. Quel métier exercez-vous ou aimeriez-vous exercer ?",
        "Qu'est-ce qui est le plus important pour vous dans un emploi : le salaire, "
        "l'ambiance, le sens ?",
        "Que pensez-vous du télétravail ? L'avez-vous déjà essayé ?",
        "Comment le travail a-t-il changé par rapport à la génération de vos parents ?",
        "Selon vous, faut-il travailler moins pour vivre mieux ?"]},
    {"title": "l'environnement", "questions": [
        "Parlons d'environnement. Quels gestes faites-vous au quotidien pour la planète ?",
        "Pensez-vous que les efforts individuels suffisent ? Pourquoi ?",
        "Faudrait-il interdire les voitures dans le centre des villes ?",
        "Que pensez-vous de la mode des vêtements bon marché ?",
        "Quelle mesure écologique trouvez-vous la plus efficace ?"]},
    {"title": "le numérique", "questions": [
        "Parlons du numérique. Combien de temps passez-vous sur votre téléphone par jour ?",
        "Les réseaux sociaux rapprochent-ils ou isolent-ils les gens, selon vous ?",
        "À quel âge un enfant devrait-il avoir un smartphone ?",
        "Les démarches administratives en ligne sont-elles un progrès pour tout le monde ?",
        "Que pensez-vous de l'intelligence artificielle dans la vie quotidienne ?"]},
    {"title": "la santé", "questions": [
        "Parlons de santé. Que faites-vous pour rester en forme ?",
        "Le sport devrait-il être obligatoire au travail ou à l'école ?",
        "Que pensez-vous des déserts médicaux et de l'accès aux soins ?",
        "Mange-t-on mieux aujourd'hui qu'il y a trente ans ?",
        "Comment gérez-vous le stress au quotidien ?"]},
    {"title": "la culture et les loisirs", "questions": [
        "Parlons de culture. Quel est le dernier film ou le dernier livre qui vous a marqué ?",
        "Les musées devraient-ils être gratuits pour tous ?",
        "Quelles traditions de votre pays aimeriez-vous faire découvrir aux Français ?",
        "La lecture est-elle menacée par les écrans ?",
        "Comment passez-vous un week-end idéal ?"]},
    {"title": "la vie en France", "questions": [
        "Parlons de votre vie en France. Qu'est-ce qui vous a le plus surpris en arrivant ?",
        "Quelles sont, pour vous, les valeurs les plus importantes de la société française ?",
        "Pourquoi est-il important de parler français pour s'intégrer ?",
        "Que conseilleriez-vous à une personne qui vient d'arriver en France ?",
        "Participez-vous à la vie associative ou locale de votre ville ?"]},
    {"title": "l'éducation", "questions": [
        "Parlons d'éducation. Quel souvenir gardez-vous de votre école ?",
        "L'école prépare-t-elle bien les jeunes au monde du travail ?",
        "Faut-il apprendre une langue étrangère dès la maternelle ?",
        "Que pensez-vous des devoirs à la maison ?",
        "Est-il possible d'apprendre un métier à tout âge ?"]},
]
RELAUNCH = {1: ["Pouvez-vous développer un peu ?", "Pourquoi ?",
                "Pouvez-vous me donner un exemple ?"],
            2: ["Je comprends, mais ce n'est pas possible pour le moment. Que proposez-vous ?",
                "Avez-vous d'autres questions ?", "Ce n'est vraiment pas possible autrement."],
            3: ["Pouvez-vous justifier votre point de vue ?",
                "Que répondriez-vous à quelqu'un qui pense le contraire ?",
                "Pouvez-vous donner un exemple concret ?"]}
EXAM_END = ("Merci, l'épreuve est terminée. Cliquez sur « Terminer et évaluer » pour obtenir "
            "votre note estimée et les commentaires.")
TYPED_WPM = 130


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().replace("’", "'"))
    return "".join(c for c in s if not unicodedata.combining(c))


def clean_markdown(md: str, limit: int = 1400) -> str:
    text = re.sub(r"^#+\s*", "", md or "", flags=re.M)
    text = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", text)
    if len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        text = text[:cut if cut > 300 else limit].rstrip() + "\n…"
    return text.strip()


def find_chapter_slug(text: str) -> str | None:
    t = f" {fold(text)} "
    best, score = None, 0
    for slug, kws in GRAMMAR_KEYWORDS.items():
        sc = sum(len(k) for k in kws if k in t)
        if sc > score:
            best, score = slug, sc
    return best


class LocalTutor:
    name = "Tuteur hors ligne"

    def __init__(self, db, rng: random.Random | None = None):
        self.db = db
        self.rng = rng or random.Random()

    # ================================================================ ouverture
    def opening(self, conv: Conversation) -> TutorReply:
        if conv.mode == MODE_TEACHER:
            extra = ""
            if conv.learner_profile:
                extra = ("\n\nD'après vos résultats, vous pourriez travailler : "
                         + " ; ".join(conv.learner_profile[:3]) + ".")
            return TutorReply(
                "Bonjour ! Je suis votre professeur. Écrivez-moi une phrase ou un court texte "
                "et je le corrige en vous expliquant les règles. Vous pouvez aussi me poser une "
                "question de grammaire (« Quand utilise-t-on le subjonctif ? ») ou de "
                "vocabulaire (« Que veut dire pallier ? »)." + extra, self.name)
        if conv.mode == MODE_CONVERSATION:
            idx = self.rng.randrange(len(TOPICS))
            conv.state.update(topic=idx, step=0, topics_done=[idx])
            return TutorReply("Bonjour ! Discutons un peu. " + TOPICS[idx]["questions"][0]
                              + "\n\n(Écrivez « autre sujet » pour changer de thème.)",
                              self.name)
        t = conv.task or {}
        conv.state.update(prompt_idx=1, relaunches=0)
        first = (t.get("examiner_prompts") or ["Bonjour, je vous écoute."])[0]
        return TutorReply(
            f"Tâche {t.get('task_number', '?')} – {t.get('title', '')}\n"
            f"Consigne : {t.get('scenario', '')}\n"
            f"Durée à l'examen : {t.get('duration_s', 0) // 60} min "
            f"{t.get('duration_s', 0) % 60:02d} s. Répondez comme à l'oral, de façon "
            f"développée. Je ne corrige pas pendant l'épreuve.\n\n"
            f"{t.get('examiner_role') or 'Examinateur'} : {first}", self.name)

    # ================================================================ réponses
    def reply(self, conv: Conversation, text: str) -> TutorReply:
        if conv.mode == MODE_TEACHER:
            return self._teacher(conv, text)
        if conv.mode == MODE_CONVERSATION:
            return self._conversation(conv, text)
        if conv.mode == MODE_EXAMINER:
            return self._examiner(conv, text)
        raise ValueError(conv.mode)

    # ---------------------------------------------------------------- professeur
    def _teacher(self, conv: Conversation, text: str) -> TutorReply:
        pending = conv.state.pop("exercise", None)
        vm = _VOCAB.search(text.strip().replace("’", "'"))
        if vm:
            return self._vocabulary(vm.group(1).strip(" .'"))
        if _QUESTION.search(fold(text).strip()):
            slug = find_chapter_slug(text)
            if slug:
                return self._lesson(conv, slug)
        if pending:
            return self._check_exercise(pending, text)
        return self._correct(text)

    def _vocabulary(self, term: str) -> TutorReply:
        with self.db.session() as s:
            w = s.execute(select(VocabWord).where(func.lower(VocabWord.word) == term.lower())
                          ).scalars().first()
            if w:
                out = [f"« {w.word} »" + (f" ({w.pos}{', ' + w.gender if w.gender else ''})"
                                         if w.pos else "") + f" : {w.definition}",
                       f"Exemple : {w.example}"]
                if w.synonyms:
                    out.append(f"Synonymes : {w.synonyms}")
                if w.collocations:
                    out.append(f"Expressions fréquentes : {w.collocations}")
                out.append("À vous : écrivez une phrase avec ce mot, je la corrige.")
                return TutorReply("\n".join(out), self.name)
            e = s.execute(select(Expression).where(or_(
                func.lower(Expression.text).contains(term.lower())))).scalars().first()
            if e:
                return TutorReply(
                    f"« {e.text} » : {e.meaning}\nExemple : {e.example}\n"
                    f"Équivalent plus simple : {e.simple_equivalent}\n"
                    f"À vous : {e.exercise}", self.name)
        return TutorReply(f"Je ne trouve pas « {term} » dans mon lexique hors ligne. "
                          "Essayez un autre mot, ou activez Claude (en ligne) pour une "
                          "explication.", self.name)

    def _lesson(self, conv: Conversation, slug: str) -> TutorReply:
        with self.db.session() as s:
            ch = s.execute(select(GrammarChapter).where(GrammarChapter.slug == slug)
                           ).scalar_one_or_none()
            if ch is None:
                return TutorReply("Je n'ai pas ce chapitre dans mes cours.", self.name)
            parts = [ch.title.upper(), clean_markdown(ch.lesson)]
            ex = (ch.simple_examples or [])[:2] + (ch.b2_examples or [])[:2]
            if ex:
                parts.append("Exemples :\n" + "\n".join(f"• {x}" for x in ex))
            exercises = [e for e in ch.exercises if e.ex_type in ("trou", "transformation",
                                                                  "qcm")]
            if exercises:
                e = self.rng.choice(exercises)
                conv.state["exercise"] = e.id
                opts = ("\n" + "\n".join(f"  {chr(97 + i)}) {o}"
                                          for i, o in enumerate(e.options))
                        if e.options else "")
                parts.append(f"Petit exercice : {e.prompt}{opts}\n(Répondez dans votre "
                             f"prochain message.)")
            parts.append(f"Pour aller plus loin : module Grammaire, chapitre « {ch.title} ».")
        return TutorReply("\n\n".join(parts), self.name)

    def _check_exercise(self, ex_id: int, text: str) -> TutorReply:
        with self.db.session() as s:
            e = s.get(GrammarExercise, ex_id)
            if e is None:
                return self._correct(text)
            accepted = e.accepted_answers()
            given = text.strip()
            if e.options and re.fullmatch(r"[a-dA-D]\)?", given):
                idx = ord(given[0].lower()) - 97
                if idx < len(e.options):
                    given = e.options[idx]
            ok, accents = LS.check_answer(given, accepted)
            LS.record_exercise(s, e, text, ok)
            if ok:
                head = "Bravo, c'est juste !"
            elif accents:
                head = (f"Presque : attention aux accents. Réponse attendue : "
                        f"« {accepted[0]} ».")
            else:
                head = f"Ce n'est pas ça. Réponse attendue : « {accepted[0]} »."
            return TutorReply(f"{head}\nCorrection : {e.explanation}\n\nVoulez-vous un autre "
                              f"exercice ? Posez-moi une question sur le même point, ou "
                              f"écrivez-moi une phrase à corriger.", self.name)

    def _correct(self, text: str) -> TutorReply:
        issues = WE.find_issues(text)
        errors = [i for i in issues if i.severity == ERROR]
        advice = [i for i in issues if i.severity != ERROR]
        out = []
        if not issues:
            out.append("Je ne relève pas d'erreur fréquente dans votre texte. 👍")
        else:
            corrected = WE.apply_fixes(text, issues)
            if corrected.strip() != text.strip():
                out.append(f"Version corrigée :\n« {corrected} »")
            for n, i in enumerate(errors + advice, 1):
                fix = (f" → « {i.replacement} »" if i.replacement else
                       f" → {i.suggestion}" if i.suggestion else "")
                kind = "Erreur" if i.severity == ERROR else "Conseil"
                out.append(f"{n}. {kind} : « {i.excerpt} »{fix}\n   {i.message} "
                           f"{i.explanation}".rstrip())
        conns = WE.find_connectors(text)
        n_sent = len(WE.sentences(text))
        tip = self._enrichment(text, conns, n_sent)
        if tip:
            out.append(tip)
        out.append(LIMITS)
        return TutorReply("\n\n".join(out), self.name,
                          corrections=[i.__dict__ for i in errors])

    def _enrichment(self, text: str, conns: dict, n_sent: int) -> str:
        with self.db.session() as s:
            if n_sent >= 2 and len(conns) < 2:
                rows = list(s.execute(select(Expression).where(Expression.kind == "connecteur")
                                      ).scalars())
                if rows:
                    picks = self.rng.sample(rows, min(3, len(rows)))
                    return ("Pour un niveau B2, articulez davantage vos idées. Essayez par "
                            "exemple : " + " ; ".join(f"« {e.text} » ({e.meaning})"
                                                      for e in picks) + ".")
            if _OPINION.search(text):
                rows = list(s.execute(select(Expression).where(
                    Expression.kind == "expression", Expression.level == "B2")).scalars())
                if rows:
                    e = self.rng.choice(rows)
                    return (f"Pour varier, vous pourriez dire : « {e.text} » — {e.meaning}. "
                            f"Exemple : {e.example}")
        return ""

    # ---------------------------------------------------------------- conversation
    def _conversation(self, conv: Conversation, text: str) -> TutorReply:
        st = conv.state
        if "topic" not in st:
            st.update(topic=0, step=0, topics_done=[0])
        if _CHANGE_TOPIC.search(text):
            return TutorReply("D'accord, changeons de sujet ! " + self._next_topic(conv),
                              self.name)
        issues = SE.oral_issues(text)
        errors = [i for i in issues if i.severity == ERROR and i.replacement][:2]
        parts = []
        if errors:
            parts.append("Petite remarque : " + " ; ".join(
                f"on dit plutôt « {i.replacement} » que « {i.excerpt} »" for i in errors) + ".")
        n = len(WE.words(text))
        conns = WE.find_connectors(text)
        if n < 8:
            parts.append(self.rng.choice(["Pouvez-vous en dire un peu plus ?",
                                          "Intéressant ! Pourquoi ?",
                                          "Pouvez-vous développer votre idée ?"]))
            return TutorReply(" ".join(parts), self.name,
                              corrections=[i.__dict__ for i in errors])
        if len(conns) >= 2:
            parts.append(self.rng.choice(["Votre réponse est bien construite.",
                                          "J'apprécie la façon dont vous enchaînez vos idées."]))
        elif _OPINION.search(text):
            parts.append(self.rng.choice(["Je vois votre point de vue.",
                                          "C'est un avis intéressant.",
                                          "Je comprends votre position."]))
        else:
            parts.append(self.rng.choice(["D'accord.", "Je vois.", "Merci pour cette réponse."]))
        st["step"] += 1
        qs = TOPICS[st["topic"]]["questions"]
        if st["step"] < len(qs):
            parts.append(qs[st["step"]])
        else:
            parts.append("Nous avons bien fait le tour de ce sujet, bravo ! "
                         + self._next_topic(conv))
        return TutorReply(" ".join(parts), self.name, corrections=[i.__dict__ for i in errors])

    def _next_topic(self, conv: Conversation) -> str:
        st = conv.state
        done = st.setdefault("topics_done", [])
        left = [i for i in range(len(TOPICS)) if i not in done] or list(range(len(TOPICS)))
        idx = self.rng.choice(left)
        done.append(idx)
        st.update(topic=idx, step=0)
        return TOPICS[idx]["questions"][0]

    # ---------------------------------------------------------------- examinateur
    def _examiner(self, conv: Conversation, text: str) -> TutorReply:
        t = conv.task or {}
        st = conv.state
        role = t.get("examiner_role") or "Examinateur"
        if st.get("ended"):
            return TutorReply(EXAM_END, self.name)
        words = sum(len(WE.words(x)) for x in conv.learner_texts())
        if words / TYPED_WPM * 60 >= t.get("duration_s", 210):
            st["ended"] = True
            return TutorReply(f"{role} : Merci beaucoup.\n\n{EXAM_END}", self.name)
        prompts = t.get("examiner_prompts") or []
        relaunch = RELAUNCH.get(t.get("task_number", 3), RELAUNCH[3])
        if len(WE.words(text)) < 15 and st.get("relaunches", 0) < len(relaunch):
            line = relaunch[st.get("relaunches", 0)]
            st["relaunches"] = st.get("relaunches", 0) + 1
            return TutorReply(f"{role} : {line}", self.name)
        i = st.get("prompt_idx", 1)
        if i < len(prompts):
            st["prompt_idx"] = i + 1
            return TutorReply(f"{role} : {prompts[i]}", self.name)
        st["ended"] = True
        return TutorReply(f"{role} : Très bien, merci.\n\n{EXAM_END}", self.name)


def evaluate_exam(conv: Conversation) -> dict:
    """Note estimée d'une simulation d'examen tapée au clavier (moteur local)."""
    t = conv.task or {}
    text = " ".join(conv.learner_texts())
    n = len(WE.words(text))
    d = round(n / TYPED_WPM * 60, 1)
    ev = SE.evaluate_oral(text, t.get("task_number", 3), t.get("duration_s", 210),
                          {"duration_s": d, "speech_s": d}, None, t.get("useful_phrases"),
                          t.get("model_answer", ""), d)
    ev.caveat = ("Réponses tapées au clavier : la durée est estimée à partir du nombre de mots "
                 f"({TYPED_WPM} mots par minute) et l'aisance orale n'est pas mesurée.")
    ev.extra["typed"] = True
    return ev.to_dict()
