from __future__ import annotations

import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "persist_publication.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=cwd,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _configure_identity(repo: Path) -> None:
    _git(repo, "config", "user.name", "Radar Test")
    _git(repo, "config", "user.email", "radar-test@example.com")


def test_persistence_reconciles_a_remote_main_race(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    publisher = tmp_path / "publisher"
    racer = tmp_path / "racer"
    subprocess.run(["git", "init", "--bare", remote], check=True)
    subprocess.run(["git", "clone", str(remote), seed], check=True)
    _configure_identity(seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _git(seed, "add", "README.md")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "branch", "-M", "main")
    _git(seed, "push", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    subprocess.run(["git", "clone", str(remote), publisher], check=True)
    subprocess.run(["git", "clone", str(remote), racer], check=True)
    _configure_identity(publisher)
    _configure_identity(racer)

    (publisher / "data").mkdir()
    history = publisher / "data" / "history.jsonl"
    history.write_text('{"run":"new"}\n', encoding="utf-8")
    (racer / "racer.txt").write_text("concurrent bot commit\n", encoding="utf-8")
    _git(racer, "add", "racer.txt")
    _git(racer, "commit", "-m", "concurrent commit")
    _git(racer, "push", "origin", "main")

    result = subprocess.run(
        [str(SCRIPT), "data/history.jsonl"],
        cwd=publisher,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    _git(publisher, "fetch", "origin", "main")
    tree = set(_git(publisher, "ls-tree", "-r", "--name-only", "origin/main").splitlines())
    assert {"README.md", "data/history.jsonl", "racer.txt"} <= tree
    messages = _git(publisher, "log", "--format=%s", "origin/main").splitlines()
    assert "concurrent commit" in messages
    assert any(message.startswith("chore: radar history") for message in messages)


def test_persistence_ignores_missing_optional_paths(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", remote], check=True)
    subprocess.run(["git", "clone", str(remote), repo], check=True)
    _configure_identity(repo)
    (repo / "data").mkdir()
    (repo / "data" / "history.jsonl").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "data/history.jsonl")
    _git(repo, "commit", "-m", "seed")
    _git(repo, "branch", "-M", "main")
    _git(repo, "push", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "data" / "history.jsonl").write_text('{"run":"next"}\n', encoding="utf-8")

    result = subprocess.run(
        [
            str(SCRIPT),
            "data/history.jsonl",
            "data/not-produced-this-run.jsonl",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(repo, "show", "origin/main:data/history.jsonl") == '{"run":"next"}'
