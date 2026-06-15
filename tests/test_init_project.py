from pathlib import Path

from radar.init_project import initialize_project


def test_initialize_project_writes_config_and_env(tmp_path: Path):
    result = initialize_project(tmp_path)

    assert result.config_path == tmp_path / "data" / "config.yaml"
    assert result.config_path.exists()
    assert (tmp_path / ".env.example").exists()
    assert (tmp_path / "data" / "runs").is_dir()

    config_text = result.config_path.read_text(encoding="utf-8")
    assert "github-openclaw" in config_text
    assert "github-nvidia-nemoclaw" in config_text
    assert "github-cline" in config_text


def test_initialize_project_does_not_overwrite_existing_config(tmp_path: Path):
    config_path = tmp_path / "data" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("version: custom\n", encoding="utf-8")

    result = initialize_project(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "version: custom\n"
    assert result.config_refreshed is False
    assert result.backup_path is None


def test_force_refreshes_config_from_seed_and_backs_up_existing(tmp_path: Path):
    config_path = tmp_path / "data" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("version: custom\n", encoding="utf-8")

    result = initialize_project(tmp_path, force=True)

    # Config now comes from the seed (carries v2 enrichment + a known source).
    refreshed = config_path.read_text(encoding="utf-8")
    assert refreshed != "version: custom\n"
    assert "enrichment" in refreshed
    assert "github-vllm" in refreshed
    assert result.config_refreshed is True

    # The prior config is preserved as a backup, not silently discarded.
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.read_text(encoding="utf-8") == "version: custom\n"


def test_force_on_fresh_project_writes_seed_without_backup(tmp_path: Path):
    result = initialize_project(tmp_path, force=True)

    assert result.config_path.exists()
    assert result.config_refreshed is True
    assert result.backup_path is None
