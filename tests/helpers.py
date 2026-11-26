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


def job(cwd, *args):
    return subprocess.run([sys.executable, JOB, *args], cwd=cwd, capture_output=True, text=True)


def fake_gh(dirpath, exit_code, output=""):
    """PATH 앞에 둘 가짜 gh. `gh pr checks` 의 종료 코드와 출력을 정한다."""
    path = os.path.join(dirpath, "gh")
    with open(path, "w") as f:
        f.write("#!/bin/sh\nprintf '%s' " + repr(output) + "\nexit " + str(exit_code) + "\n")
    os.chmod(path, 0o755)
    return dirpath
