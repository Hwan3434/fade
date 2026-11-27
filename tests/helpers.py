import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
JOB = os.path.join(ROOT, "skills", "job", "job.py")
GATE = os.path.join(ROOT, "hooks", "merge_gate.py")
PERMISSION = os.path.join(ROOT, "hooks", "permission_gate.py")
DESTRUCTIVE = os.path.join(ROOT, "hooks", "destructive_gate.py")
AGENTS = os.path.join(ROOT, "agents")

# 테스트가 부르는 job.py 와 훅이 사용자의 실제 실수 기록(~/.claude/fade/mistakes.jsonl)에 쓰지 않게,
# 이 모듈을 읽는 순간 모든 하위 프로세스가 물려받을 기록 경로를 임시 폴더로 바꾼다.
_MISTAKES_DIR = tempfile.TemporaryDirectory()
os.environ["FADE_MISTAKES"] = os.path.join(_MISTAKES_DIR.name, "mistakes.jsonl")


def mistakes(path=None):
    """실수 기록의 줄들. 파일이 없으면 빈 목록."""
    path = path or os.environ["FADE_MISTAKES"]
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def git_repo():
    d = tempfile.TemporaryDirectory()
    subprocess.run(["git", "init", "-q", d.name], check=True)
    return d


def commit_and_switch(cwd, branch):
    """빈 커밋을 하나 만들고 새 브랜치로 옮긴다. CI 러너에는 git 사용자 정보가 없어 여기서 준다."""
    subprocess.run(["git", "-c", "user.name=fade-test", "-c", "user.email=fade-test@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "x"], cwd=cwd, check=True)
    subprocess.run(["git", "switch", "-q", "-c", branch], cwd=cwd, check=True)


def commit_file(cwd, name, text, message="수정"):
    """파일 하나를 쓰고 그것만 담아 커밋한다."""
    path = os.path.join(cwd, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    subprocess.run(["git", "add", name], cwd=cwd, check=True)
    subprocess.run(["git", "-c", "user.name=fade-test", "-c", "user.email=fade-test@example.invalid",
                    "commit", "-q", "-m", message], cwd=cwd, check=True)


def job(cwd, *args, env=None):
    return subprocess.run([sys.executable, JOB, *args], cwd=cwd, capture_output=True, text=True, env=env)


def fake_gh(dirpath, exit_code, output="", error="", head=None, head_exit=0):
    """PATH 앞에 둘 가짜 gh.

    `gh pr checks` 는 exit_code, output, error 로 답한다. `gh pr view` 는 head 가 있으면 그 커밋을 내고
    head_exit 로 끝나며, head 가 없으면 PR 을 못 찾은 오류로 끝난다.
    """
    path = os.path.join(dirpath, "gh")
    if head is None:
        view = "printf '%s' 'no pull requests found' >&2\n  exit 1\n"
    else:
        view = "printf '%s\\n' " + repr(head) + "\n  exit " + str(head_exit) + "\n"
    with open(path, "w") as f:
        f.write("#!/bin/sh\nif [ \"$2\" = view ]; then\n  " + view + "fi\n"
                "printf '%s' " + repr(output) + "\nprintf '%s' " + repr(error) + " >&2\nexit "
                + str(exit_code) + "\n")
    os.chmod(path, 0o755)
    return dirpath
