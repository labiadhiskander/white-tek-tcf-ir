"""Génère tcfmaster/content/data/verbs.json : tables de conjugaison complètes.

Un petit moteur de conjugaison produit les 12 temps à partir des formes de base
de chaque verbe (présent, radicaux du futur et de l'imparfait, participe passé,
type de passé simple). Les verbes irréguliers sont décrits explicitement.
"""
from __future__ import annotations

import json
from pathlib import Path

VOWELS = "aeiouyéèêâîôûh"
PERS = ["je", "tu", "il", "nous", "vous", "ils"]
REFL = ["me", "te", "se", "nous", "vous", "se"]
IMP_END = ["ais", "ais", "ait", "ions", "iez", "aient"]
SUBJ_END = ["e", "es", "e", "ions", "iez", "ent"]
FUT_END = ["ai", "as", "a", "ons", "ez", "ont"]
PS_END = {
    "a": ["ai", "as", "a", "âmes", "âtes", "èrent"],
    "i": ["is", "is", "it", "îmes", "îtes", "irent"],
    "u": ["us", "us", "ut", "ûmes", "ûtes", "urent"],
    "in": ["ins", "ins", "int", "înmes", "întes", "inrent"],
}


def _elide(word: str, nxt: str) -> str:
    if word in ("je", "me", "te", "se") and nxt[:1].lower() in VOWELS:
        return word[0] + "'"
    return word + " "


def with_pronoun(i: int, form: str, refl: bool = False, subj: bool = False) -> str:
    core = form
    if refl:
        core = _elide(REFL[i], core) + core
    out = _elide(PERS[i], core) + core
    if subj:
        out = ("qu'" if PERS[i] in ("il", "ils") else "que ") + out
    return out


def soft(inf: str, stem: str, ending: str) -> str:
    """commencer -> commençons ; manger -> mangeons."""
    if ending[:1] in "aâo":
        if inf.endswith("cer"):
            return stem[:-1] + "ç" + ending
        if inf.endswith("ger"):
            return stem + "e" + ending
    return stem + ending


class Verb:
    def __init__(self, inf, group, pres, pp, ps, aux="avoir", refl=False, fut=None,
                 imp_stem=None, subj=None, impv=None, impersonal=False):
        self.inf, self.group, self.pres, self.pp, self.ps = inf, group, pres, pp, ps
        self.aux, self.refl, self.impersonal = aux, refl, impersonal
        self.fut = fut or (inf[:-1] if inf.endswith("re") else inf)
        self.imp_stem = imp_stem
        self.subj = subj
        self.impv = impv

    # -- formes nues (sans pronom) --
    def bare_imparfait(self):
        if self.group == 1:
            st = getattr(self, 'stem1', self.inf[:-2])
            return [soft(self.inf, st, e) for e in IMP_END]
        st = self.imp_stem or self.pres[3][:-3]
        return [st + e for e in IMP_END]

    def bare_futur(self):
        return [self.fut + e for e in FUT_END]

    def bare_conditionnel(self):
        return [self.fut + e for e in IMP_END]

    def bare_subjonctif(self):
        if isinstance(self.subj, list):
            return self.subj
        if isinstance(self.subj, tuple):
            s1, s2 = self.subj
        else:
            s1 = self.pres[5][:-3]
            s2 = (self.inf[:-2] if self.group == 1 else (self.imp_stem or self.pres[3][:-3]))
        return [(s2 if i in (3, 4) else s1) + e for i, e in enumerate(SUBJ_END)]

    def bare_ps(self):
        if isinstance(self.ps, list):
            return self.ps
        kind, stem = self.ps
        return [soft(self.inf, stem, e) if self.group == 1 else stem + e
                for e in PS_END[kind]]

    def imperatif(self):
        if self.impersonal or self.impv == []:
            return None
        forms = self.impv or [self.pres[1], self.pres[3], self.pres[4]]
        if not self.impv and forms[0].endswith(("es", "as")):
            forms = [forms[0][:-1]] + forms[1:]
        if self.refl:
            return [f"{forms[0]}-toi", f"{forms[1]}-nous", f"{forms[2]}-vous"]
        return forms

    def agreed_pp(self, i):
        if self.aux == "etre" or self.refl:
            base = self.pp
            if i == 2:
                return base
            if i == 5:
                return base if base.endswith("s") else base + "s"
            if i >= 3:
                return base + ("(e)s" if not base.endswith("s") else "(es)")
            return base + "(e)"
        return self.pp


def _simple(v: Verb, bare: list[str], subj=False) -> list[str]:
    if v.impersonal:
        return ["", "", with_pronoun(2, bare[2], subj=subj), "", "", ""]
    return [with_pronoun(i, f, v.refl, subj) for i, f in enumerate(bare)]


def conjugate(v: Verb, aux_tables: dict) -> dict:
    t = {
        "present": _simple(v, v.pres),
        "imparfait": _simple(v, v.bare_imparfait()),
        "futur_simple": _simple(v, v.bare_futur()),
        "conditionnel_present": _simple(v, v.bare_conditionnel()),
        "subjonctif_present": _simple(v, v.bare_subjonctif(), subj=True),
        "passe_simple": _simple(v, v.bare_ps()),
    }
    aux = aux_tables["etre" if (v.aux == "etre" or v.refl) else "avoir"]
    for name, base, subj in (("passe_compose", "present", False),
                             ("plus_que_parfait", "imparfait", False),
                             ("futur_anterieur", "futur_simple", False),
                             ("conditionnel_passe", "conditionnel_present", False),
                             ("subjonctif_passe", "subjonctif_present", True)):
        forms = []
        for i in range(6):
            if v.impersonal and i != 2:
                forms.append("")
                continue
            forms.append(with_pronoun(i, aux[base][i], v.refl, subj) + " " + v.agreed_pp(i))
        t[name] = forms
    imp = v.imperatif()
    if imp:
        t["imperatif"] = imp
    order = ["present", "passe_compose", "imparfait", "plus_que_parfait", "futur_simple",
             "futur_anterieur", "conditionnel_present", "conditionnel_passe",
             "subjonctif_present", "subjonctif_passe", "imperatif", "passe_simple"]
    return {k: t[k] for k in order if k in t}


# ------------------------------------------------------------ constructeurs
def er(inf, aux="avoir", refl=False, mute=None, fut=None):
    base = inf[3:] if inf.startswith("se ") else (inf[2:] if inf.startswith("s'") else inf)
    st = base[:-2]
    m = mute or st
    pres = [m + "e", m + "es", m + "e", soft(inf, st, "ons"), st + "ez", m + "ent"]
    if fut is None:
        fut = (m + "er") if mute else base
    subj = (m, st)
    v = Verb(inf, 1, pres, st + "é", ("a", st), aux=aux, refl=refl, fut=fut, subj=subj)
    v.stem1 = st
    return v


def ir2(inf):
    st = inf[:-2]
    pres = [st + "is", st + "is", st + "it", st + "issons", st + "issez", st + "issent"]
    return Verb(inf, 2, pres, st + "i", ("i", st))


def v3(inf, pres, pp, ps, **kw):
    if isinstance(pres, str):
        pres = pres.split()
    return Verb(inf, 3, pres, pp, ps, **kw)


def dre(inf, aux="avoir"):
    s = inf[:-2]
    return v3(inf, [s + "s", s + "s", s, s + "ons", s + "ez", s + "ent"], s + "u", ("i", s),
              aux=aux)


def venir_like(inf, p, aux="avoir", refl=False):
    return v3(inf, [p + "iens", p + "iens", p + "ient", p + "enons", p + "enez",
                    p + "iennent"], p + "enu", ("in", p), aux=aux, refl=refl, fut=p + "iendr")


def prendre_like(inf, p):
    return v3(inf, [p + "rends", p + "rends", p + "rend", p + "renons", p + "renez",
                    p + "rennent"], p + "ris", ("i", p + "r"))


def mettre_like(inf, p):
    return v3(inf, [p + "ets", p + "ets", p + "et", p + "ettons", p + "ettez", p + "ettent"],
              p + "is", ("i", p))


def uire(inf):
    s = inf[:-3]  # conduire -> condu
    return v3(inf, [s + "is", s + "is", s + "it", s + "isons", s + "isez", s + "isent"],
              s + "it", ("i", s + "is"))


def eindre(inf, a):
    """craindre (a='ai'), peindre (a='ei'), joindre (a='oi')."""
    s = inf[: inf.index(a)]
    n = s + a + "n"
    g = s + a + "gn"
    return v3(inf, [n + "s", n + "s", n + "t", g + "ons", g + "ez", g + "ent"], n + "t",
              ("i", g))


def vrir(inf):
    s = inf[:-2]
    return v3(inf, [s + "e", s + "es", s + "e", s + "ons", s + "ez", s + "ent"],
              s[:-1] + "ert", ("i", s))


def tir(inf, aux="avoir"):
    """partir, sortir, dormir, sentir, servir."""
    s = inf[:-3]
    c = inf[-3]
    return v3(inf, [s + "s", s + "s", s + "t", s + c + "ons", s + c + "ez", s + c + "ent"],
              inf[:-2] + "i", ("i", inf[:-2]), aux=aux)


def verbs() -> list[Verb]:
    E = "etre"
    vs = [
        v3("être", "suis es est sommes êtes sont", "été", ("u", "f"), fut="ser", imp_stem="ét",
           subj=["sois", "sois", "soit", "soyons", "soyez", "soient"],
           impv=["sois", "soyons", "soyez"]),
        v3("avoir", "ai as a avons avez ont", "eu", ("u", "e"), fut="aur",
           subj=["aie", "aies", "ait", "ayons", "ayez", "aient"],
           impv=["aie", "ayons", "ayez"]),
        v3("aller", "vais vas va allons allez vont", "allé", ("a", "all"), aux=E, fut="ir",
           subj=("aill", "all")),
        v3("faire", "fais fais fait faisons faites font", "fait", ("i", "f"), fut="fer",
           subj=("fass", "fass")),
        v3("dire", "dis dis dit disons dites disent", "dit", ("i", "d")),
        v3("pouvoir", "peux peux peut pouvons pouvez peuvent", "pu", ("u", "p"), fut="pourr",
           subj=("puiss", "puiss"), impv=[]),
        v3("vouloir", "veux veux veut voulons voulez veulent", "voulu", ("u", "voul"),
           fut="voudr", subj=("veuill", "voul"), impv=["veuille", "veuillons", "veuillez"]),
        v3("devoir", "dois dois doit devons devez doivent", "dû", ("u", "d"), fut="devr"),
        v3("savoir", "sais sais sait savons savez savent", "su", ("u", "s"), fut="saur",
           subj=("sach", "sach"), impv=["sache", "sachons", "sachez"]),
        venir_like("venir", "v", aux=E), venir_like("devenir", "dev", aux=E),
        venir_like("revenir", "rev", aux=E), venir_like("tenir", "t"),
        venir_like("obtenir", "obt"), venir_like("se souvenir", "souv", refl=True),
        prendre_like("prendre", "p"), prendre_like("apprendre", "app"),
        prendre_like("comprendre", "comp"),
        mettre_like("mettre", "m"), mettre_like("permettre", "perm"),
        mettre_like("promettre", "prom"),
        v3("voir", "vois vois voit voyons voyez voient", "vu", ("i", "v"), fut="verr"),
        v3("prévoir", "prévois prévois prévoit prévoyons prévoyez prévoient", "prévu",
           ("i", "prév"), fut="prévoir"),
        v3("croire", "crois crois croit croyons croyez croient", "cru", ("u", "cr")),
        v3("boire", "bois bois boit buvons buvez boivent", "bu", ("u", "b")),
        v3("lire", "lis lis lit lisons lisez lisent", "lu", ("u", "l")),
        v3("écrire", "écris écris écrit écrivons écrivez écrivent", "écrit", ("i", "écriv")),
        v3("décrire", "décris décris décrit décrivons décrivez décrivent", "décrit",
           ("i", "décriv")),
        v3("s'inscrire", "inscris inscris inscrit inscrivons inscrivez inscrivent", "inscrit",
           ("i", "inscriv"), refl=True, fut="inscrir"),
        v3("vivre", "vis vis vit vivons vivez vivent", "vécu", ("u", "véc")),
        v3("suivre", "suis suis suit suivons suivez suivent", "suivi", ("i", "suiv")),
        v3("connaître", "connais connais connaît connaissons connaissez connaissent", "connu",
           ("u", "conn")),
        v3("paraître", "parais parais paraît paraissons paraissez paraissent", "paru",
           ("u", "par")),
        v3("naître", "nais nais naît naissons naissez naissent", "né", ("i", "naqu"), aux=E),
        tir("partir", aux=E), tir("sortir", aux=E), tir("dormir"), tir("sentir"),
        tir("servir"),
        vrir("ouvrir"), vrir("offrir"), vrir("découvrir"),
        v3("recevoir", "reçois reçois reçoit recevons recevez reçoivent", "reçu", ("u", "reç"),
           fut="recevr"),
        v3("apercevoir", "aperçois aperçois aperçoit apercevons apercevez aperçoivent",
           "aperçu", ("u", "aperç"), fut="apercevr"),
        dre("attendre"), dre("entendre"), dre("répondre"), dre("vendre"), dre("perdre"),
        dre("rendre"), dre("descendre", aux=E),
        v3("battre", "bats bats bat battons battez battent", "battu", ("i", "batt")),
        v3("interrompre", "interromps interromps interrompt interrompons interrompez "
           "interrompent", "interrompu", ("i", "interromp")),
        uire("conduire"), uire("construire"), uire("produire"), uire("traduire"),
        eindre("craindre", "ai"), eindre("peindre", "ei"), eindre("joindre", "oi"),
        eindre("rejoindre", "oi"),
        v3("plaire", "plais plais plaît plaisons plaisez plaisent", "plu", ("u", "pl")),
        v3("falloir", ["", "", "faut", "", "", ""], "fallu", ["", "", "fallut", "", "", ""],
           fut="faudr", imp_stem="fall", subj=["", "", "faille", "", "", ""], impersonal=True),
        v3("pleuvoir", ["", "", "pleut", "", "", ""], "plu", ["", "", "plut", "", "", ""],
           fut="pleuvr", imp_stem="pleuv", subj=["", "", "pleuve", "", "", ""],
           impersonal=True),
        v3("courir", "cours cours court courons courez courent", "couru", ("u", "cour"),
           fut="courr"),
        v3("mourir", "meurs meurs meurt mourons mourez meurent", "mort", ("u", "mour"),
           aux=E, fut="mourr"),
        v3("valoir", "vaux vaux vaut valons valez valent", "valu", ("u", "val"), fut="vaudr",
           subj=("vaill", "val")),
        v3("résoudre", "résous résous résout résolvons résolvez résolvent", "résolu",
           ("u", "résol")),
        v3("acquérir", "acquiers acquiers acquiert acquérons acquérez acquièrent", "acquis",
           ("i", "acqu"), fut="acquerr"),
        v3("rire", "ris ris rit rions riez rient", "ri", ("i", "r")),
        v3("convaincre", "convaincs convaincs convainc convainquons convainquez "
           "convainquent", "convaincu", ("i", "convainqu")),
        # 2e groupe
        *[ir2(x) for x in ("finir", "choisir", "réussir", "réfléchir", "grandir", "remplir",
                           "agir", "établir", "investir", "réagir", "garantir", "saisir")],
        # 1er groupe réguliers
        *[er(x) for x in ("parler", "aimer", "travailler", "habiter", "chercher", "donner",
                          "trouver", "penser", "demander", "écouter", "regarder", "passer",
                          "jouer", "étudier", "oublier", "utiliser", "proposer", "organiser",
                          "expliquer", "participer", "décider", "présenter", "améliorer",
                          "continuer", "montrer", "accepter", "refuser", "créer",
                          "contacter", "envisager", "partager", "remplacer", "influencer",
                          "encourager", "consommer", "protéger", "développer", "souhaiter",
                          "économiser", "recycler", "postuler", "louer", "signer")],
        *[er(x, aux=E) for x in ("arriver", "entrer", "rester", "tomber", "monter",
                                 "retourner", "rentrer")],
        er("commencer"), er("manger"), er("voyager"),
        er("appeler", mute="appell"), er("jeter", mute="jett"),
        er("acheter", mute="achèt"), er("se lever", refl=True, mute="lèv"),
        er("se promener", refl=True, mute="promèn"),
        er("préférer", mute="préfèr", fut="préférer"),
        er("espérer", mute="espèr", fut="espérer"),
        er("répéter", mute="répèt", fut="répéter"),
        er("envoyer", mute="envoi", fut="enverr"),
        er("payer", mute="pai", fut="paier"), er("essayer", mute="essai", fut="essaier"),
        er("employer", mute="emploi", fut="emploier"),
        er("nettoyer", mute="nettoi", fut="nettoier"),
        er("s'habituer", refl=True), er("s'occuper", refl=True),
        er("se reposer", refl=True), er("se dépêcher", refl=True),
        er("s'intéresser", refl=True), er("se tromper", refl=True),
    ]
    return vs


def build(src_root: Path, out_root: Path) -> list[str]:
    vs = verbs()
    aux = {}
    for name in ("être", "avoir"):
        v = next(x for x in vs if x.inf == name)
        aux["etre" if name == "être" else "avoir"] = {
            "present": v.pres, "imparfait": v.bare_imparfait(), "futur_simple": v.bare_futur(),
            "conditionnel_present": v.bare_conditionnel(),
            "subjonctif_present": v.bare_subjonctif()}
    out, errors = [], []
    for v in vs:
        aux_name = "être" if (v.aux == "etre" or v.refl) else "avoir"
        try:
            out.append({"infinitive": v.inf, "group": v.group, "auxiliary": aux_name,
                        "conjugations": conjugate(v, aux)})
        except Exception as e:  # pragma: no cover
            errors.append(f"verbe {v.inf}: {e}")
    (out_root / "verbs.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"verbes : {len(out)} verbes conjugués à 12 temps")
    return errors


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    for e in build(root / "content_src", root / "tcfmaster" / "content" / "data"):
        print("ERREUR:", e)
