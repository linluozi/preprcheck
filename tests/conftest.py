import subprocess

import pytest


class RepoBuilder:
    def __init__(self, path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args, check=True):
        proc = subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, check=False
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {args} failed: {proc.stderr}")
        return proc

    def commit(self, relpath, content, message="change"):
        target = self.path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def head(self, relpath):
        return self.git("show", f"HEAD:{relpath}").stdout

    def remove(self, relpath, message="remove"):
        self.git("rm", "-q", relpath)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    return RepoBuilder(tmp_path / "upstream")