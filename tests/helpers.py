import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
JOB = os.path.join(ROOT, "skills", "job", "job.py")
GATE = os.path.join(ROOT, "hooks", "merge_gate.py")


def git_repo():
    d = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", d.name], check=True)
    return d


def commit_and_switch(cwd, branch):
    """빈 커밋을 하나 만들고 새 브랜치로 옮긴다. CI 러너에는 git 사용자 정보가 없어 여기서 준다."""
    subprocess.run(["git", "-c", "user.name=fade-test", "-c", "user.email=fade-test@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "x"], cwd=cwd, check=True)
    subprocess.run(["git", "switch", "-q", "-c", branch], cwd=cwd, check=True)


def job(cwd, *args):
    return subprocess.run([sys.executable, JOB, *args], cwd=cwd, capture_output=True, text=True)


def fake_gh(dirpath, exit_code, output=""):
    """PATH 앞에 둘 가짜 gh. `gh pr checks` 의 종료 코드와 출력을 정한다."""
    path = os.path.join(dirpath, "gh")
    with open(path, "w") as f:
        f.write("#!/bin/sh\nprintf '%s' " + repr(output) + "\nexit " + str(exit_code) + "\n")
    os.chmod(path, 0o755)
    return dirpath
