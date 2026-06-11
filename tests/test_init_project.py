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

    initialize_project(tmp_path)

    assert config_path.read_text(encoding="utf-8") == "version: custom\n"
