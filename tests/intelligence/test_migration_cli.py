from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app

from .test_migration import seed_legacy_root


def test_intelligence_migrate_prints_import_report(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)

    result = CliRunner().invoke(
        app,
        ["intelligence-migrate", "--root", str(tmp_path)],
    )

    assert result.exit_code == 0, result.stdout
    assert '"models_imported": 1' in result.stdout
    assert (tmp_path / "data" / "intelligence.db").exists()


def test_intelligence_shadow_check_passes_after_import(tmp_path: Path) -> None:
    seed_legacy_root(tmp_path)
    runner = CliRunner()
    runner.invoke(app, ["intelligence-migrate", "--root", str(tmp_path)])

    result = runner.invoke(
        app,
        ["intelligence-shadow", "--root", str(tmp_path), "--check"],
    )

    assert result.exit_code == 0, result.stdout
    assert '"is_equivalent": true' in result.stdout
