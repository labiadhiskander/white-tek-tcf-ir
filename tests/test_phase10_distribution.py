"""Phase 10 : distribution (PyInstaller, Inno Setup, CI), mises à jour, guide."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import tcfmaster
from tcfmaster.core.app_context import AppContext
from tcfmaster.core.logging_setup import setup_logging
from tcfmaster.services import settings as S
from tcfmaster.services import updates as UP

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- versions
def test_version_comparison():
    assert UP.parse_version("v1.2.3") == (1, 2, 3)
    assert UP.parse_version("2.0") == (2, 0, 0)
    assert UP.is_newer("v1.0.1", "1.0.0") and UP.is_newer("1.10.0", "1.9.9")
    assert not UP.is_newer("1.0.0", "1.0.0") and not UP.is_newer("0.9", "1.0.0")
    assert re.fullmatch(r"\d+\.\d+\.\d+", tcfmaster.__version__)


def test_update_check_with_release():
    rel = {"tag_name": "v9.0.0", "html_url": "https://github.com/x/releases/v9.0.0",
           "body": "Nouveautés", "assets": [
               {"name": "WhiteTekTCF-Setup-9.0.0.exe",
                "browser_download_url": "https://github.com/x/Setup.exe"}]}
    info = UP.check(fetch=lambda url: rel, current="1.0.0")
    assert info.available and info.latest == "9.0.0" and info.url.endswith("Setup.exe")
    info = UP.check(fetch=lambda url: {"tag_name": "v1.0.0"}, current="1.0.0")
    assert not info.available and info.error is None


def test_update_check_failures_are_quiet():
    def boom(url):
        raise OSError("réseau")
    assert UP.check(fetch=boom).error and not UP.check(fetch=boom).available
    assert "sécurisée" in UP.check("http://exemple.org/x").error
    assert UP.check(fetch=lambda u: {}).error


# ---------------------------------------------------------------- empaquetage
def test_packaging_files_are_consistent():
    spec = (ROOT / "packaging" / "tcfmaster.spec").read_text(encoding="utf-8")
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert 'name="WhiteTekTCF"' in spec and "launch.py" in spec
    for rel in ("content\" / \"data", "assets", "docs"):
        assert rel in spec
    assert (ROOT / "packaging" / "launch.py").is_file()
    assert (ROOT / "tcfmaster" / "assets" / "app.ico").stat().st_size > 1000
    assert "WhiteTekTCF.exe" in iss and "French.isl" in iss
    assert "dist\\WhiteTekTCF\\*" in iss and "PrivilegesRequired=lowest" in iss
    # même nom d'exécutable partout
    assert 'name="WhiteTekTCF"' in spec and '#define AppExe "WhiteTekTCF.exe"' in iss


def test_workflows_build_and_test():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    rel = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "pytest" in ci and "windows-latest" in ci
    for step in ("fetch_vosk_model.py", "PyInstaller", "iscc", "upload-artifact",
                 "action-gh-release", "workflow_dispatch"):
        assert step in rel, step
    # Le quota de stockage des artefacts ne doit jamais empêcher la publication.
    assert rel.index("action-gh-release") < rel.index("upload-artifact")
    art = rel[rel.index("Artefact téléchargeable"):]
    assert "continue-on-error: true" in art and "retention-days" in art


def test_version_info_writer(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("wvi", ROOT / "tools" / "write_version_info.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "packaging").mkdir()
    assert mod.main() == 0
    txt = (tmp_path / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    assert tcfmaster.__version__ in txt and "WhiteTekTCF.exe" in txt


# ---------------------------------------------------------------- guide et interface
def test_user_guide_is_complete_and_honest():
    from tcfmaster.ui.help_settings import guide_text
    g = guide_text()
    for section in ("Installation", "examen blanc", "Expression orale", "tuteur IA",
                    "Exercices personnalisés", "tableau de bord", "Sauvegardes",
                    "Mises à jour", "En cas de problème"):
        assert section.lower() in g.lower(), section
    assert "pas des résultats officiels" in g or "jamais des résultats officiels" in g
    assert "jamais déclaré prêt" in g


def test_help_card_and_startup_check(db, tmp_paths, qapp, monkeypatch):
    from tcfmaster.ui import speaking as SPK
    from tcfmaster.ui.help_settings import GuideDialog, HelpSettingsCard
    from tcfmaster.ui.main_window import MainWindow
    SPK.RUN_SYNC = True
    ctx = AppContext(paths=tmp_paths, db=db, log=setup_logging(tmp_paths.logs))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: shown.append(a[2])
                        or QMessageBox.No)
    calls = []
    monkeypatch.setattr(UP, "_fetch", lambda url: calls.append(url) or {"tag_name": "v99.0.0"})
    card = HelpSettingsCard(ctx)
    card.refresh()
    assert card.auto.isChecked()
    card.check_now()
    assert calls and "99.0.0" in shown[-1]
    d = GuideDialog()
    assert "Guide utilisateur" in d.view.toPlainText()
    win = MainWindow(ctx)
    n = len(calls)
    with db.session() as s:
        S.set_(s, "check_updates", False)
    win.check_updates_on_start()
    assert len(calls) == n                     # désactivé : aucune requête
    card.refresh()
    assert not card.auto.isChecked()
    card.auto.setChecked(True)
    win.check_updates_on_start()
    assert len(calls) == n + 1
