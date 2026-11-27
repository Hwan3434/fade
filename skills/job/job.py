#!/usr/bin/env python3
"""job 의 단계 기록. 병합 직전에 fade 훅(hooks/merge_gate.py)이 이 기록을 본다.

플러그인의 bin/job.py 가 이 파일을 부르고, Claude Code 가 bin/ 을 Bash 도구의 PATH 에 두니 경로 없이 `job.py <명령>` 으로 부른다.
기록 명령은 무엇을 기록했는지 한두 줄만 찍는다. 기록 전체는 show, 병합 전에 빠진 것은 check 에서만 나온다.
답을 받지 못한 질문이 있으면 기록 명령 뒤에도 그 사실을 한 줄 덧붙인다.

기록은 작업 중인 워크트리의 git 폴더 안 fade-job.json 한 파일이다. 커밋되지 않고 워크트리와 함께 사라진다.
병합 조건의 green 과 리뷰는 지금 커밋에서 찍힌 것만 친다. 증거와 써 보기는 지금 커밋에서 찍혔거나,
기대는 경로(--paths)를 적었고 찍은 커밋 뒤로 그 경로가 바뀌지 않았으면 친다. 낡은 것이 하나라도 남으면 막는다.
실수 기록은 작업과 레포를 넘어 모이는 한 파일(~/.claude/fade/mistakes.jsonl, 환경 변수 FADE_MISTAKES 로 바꾼다)이다.
stop 과 slip, 그리고 병합 훅과 승인 창 훅이 막을 때 한 줄씩 붙는다. 레포가 OS 임시 폴더 아래에 있으면(테스트, 써 보기)
FADE_MISTAKES 를 정하지 않은 동안 쓰지 않는다. PR 을 기록하면 이 작업에서 붙인 줄의 빈 pr 칸을 채운다.

  job.py start   <제목> [--pr-only] [--unattended]
                                         작업을 시작한다. PR 까지만이면 --pr-only, 계획서가 「사용자: 없음」이면 --unattended
                                         옵션은 다른 인자의 앞뒤 어디에 써도 읽는다(--paths 는 뒤의 인자를 모두 경로로 받으니 맨 끝에 쓴다). 모르는 옵션(-- 로 시작하고 띄어쓰기가 없는 인자)은
                                         어느 명령에서든 받지 않는다. -- 로 시작하는 한 단어를 제목, 요약, 이유 같은 값으로 넣으려면
                                         그 앞에 -- 를 따로 둔다. 그 뒤의 인자는 모두 값이다 (job.py stop -- --x)
  job.py scope   merge|pr                범위를 바꾼다 (사용자가 범위를 바꿨을 때)
  job.py red     <테스트 명령>           명령을 돌려 실패할 때만 기록한다 (구현 전)
  job.py green                           red 의 명령을 다시 돌려 통과할 때만 기록한다 (구현 후)
  job.py no-test <이유>                  레포에 테스트 실행 장치가 없을 때 red·green 대신 이유를 적는다
  job.py evidence <완료 기준> <파일>... [--paths <경로>...]
                                         스크린샷, 로그 같은 증거 파일을 기준에 붙인다. 이 레포 밖의 OS 임시 폴더에 있는
                                         파일은 지워질 수 있어 받지 않는다(tried 도 같다). git 폴더 안 fade-try/ 에 둔다
  job.py log     <완료 기준> <명령> [--paths <경로>...]
                                         명령을 돌려 출력 전체를 파일로 남기고 증거로 붙인다. 출력은 종료 코드가 0 이 아닐 때만
                                         끝 40줄을 찍는다. 전체는 로그 파일에 있다
  job.py tried   <무엇을 어떻게> <파일>... [--paths <경로>...]
                                         직접 써 본 기록과 그 화면·출력 파일
                                         --paths 는 그 증거나 써 보기가 기대는 레포 안의 파일과 폴더다. 적으면 그 경로가
                                         바뀌지 않는 동안 뒤 커밋에서도 유효하고, 적지 않으면 찍은 커밋에서만 유효하다.
                                         같은 기준의 같은 명령(evidence 는 같은 파일, tried 는 같은 글)으로 다시 남기면 앞의 것을 바꾼다
  job.py drop    <완료 기준> | --tried    그 기준에 붙인 증거를, --tried 면 써 보기를 모두 지운다
  job.py try-na  <이유>                  써 볼 화면도 명령도 없는 작업일 때
  job.py human   <사람이 볼 것>           사람만 판정할 수 있는 것이 남았을 때. 직접 써 보기를 대신하고, 병합을 막는다
  job.py review-files <base>             명세 리뷰어를 띄울지 판단할 재료를 알린다. 첫 줄은 base 와의 diff 의 파일 수와 줄 수
                                         (더한 줄 + 뺀 줄), 셋째 줄부터는 파일마다 더한 줄, 뺀 줄, 경로다. 명세 리뷰어에게 줄 show
                                         출력과 diff 를 워크트리 안 .fade-review/ (git 이 무시하는 폴더)에 쓴다. 명세 리뷰어가 본
                                         커밋이 있으면 그 뒤에 고친 부분만, 없으면 base 와의 전체를 쓴다(둘째 줄이 어느 쪽인지 알린다).
                                         계획서 원문은 부르는 쪽이 plan.md 로 쓴다
  job.py review  <남은 막는 지적 수> [<요약>] [--spec | --minor]
                                         코드 리뷰 결과. 지금 커밋에서 남은 막는 지적이 0 이어야 병합한다
                                         --spec 은 이 커밋에서 만든 review-files 의 입력으로 명세 리뷰어도 봤다는 뜻이다.
                                         --spec 도 --minor 도 없으면 명세 리뷰어를 띄우지 않은 이유를 요약에 적어야 받는다
                                         --minor 는 막는 지적이 0 이 된 뒤 사소한 지적을 한 커밋으로 고치고, 그 커밋의 diff 만
                                         버그 축으로 본 리뷰다. 앞 리뷰가 막는 지적 0 이고 그 뒤의 커밋이 하나일 때만 받는다
  job.py door    one-way|two-way <이유와 영향 범위>
                                         되돌릴 수 있는가. 기록이 없거나 one-way(한쪽 문)면 병합을 막는다
  job.py ask     <질문>                  사용자에게 물은 것을 남긴다. 답을 적기 전까지 show 의 상태 줄 바로 아래에 번호째 나온다.
                                         보고에는 첫 줄인 기록 주소 다음에 번호째 다시 적는다
  job.py answered <번호> <답>            사용자에게 받은 답을 적는다
  job.py stop    <이유>                  해결하지 못했거나 사용자 결정이 필요해 멈춘다. 병합을 막고 실수 기록에 남긴다
  job.py slip    review|ci|try|user <key> <무엇을 잘못했나>
                                         리뷰에서 고친 막는 지적, CI 실패, 써 보기(tester)가 찾은 버그, 사용자 지적을 실수 기록에
                                         남긴다. key 는 같은 실수끼리 묶는 이름(영문 소문자, 숫자, -)이다. 같은 실수의 key 가
                                         이미 있으면 그것을 쓴다. key 를 빼면 받지 않고 있는 key 를 알린다
  job.py mark    <줄 번호> key|handled <값>
                                         실수 기록 한 줄의 key(같은 실수끼리 묶는 이름)나 처리를 적는다. git 레포 밖에서도 돈다
  job.py pr      <PR 주소>
  job.py check                           병합 조건을 본다. 빠진 것을 모두 찍고, 있으면 종료 코드 1
  job.py merged  <병합 커밋> [<base CI 결과>]
  job.py show [--full] [--save]          기록. 첫 줄은 상태다. 기본은 완료 기준마다 한 줄(이름, 종료 코드, 커밋)이다.
                                         --full 이면 명령 전문, 파일 경로, 로그 내용도 붙인다. PR 의 기록 댓글에는 --full 을 단다.
                                         --save 는 --full 의 출력을 찍지 않고 메인 체크아웃의 git 폴더 안 fade-job-reports/ 의
                                         파일(워크트리가 지워져도 남는다)에 쓰고 그 절대 경로만 찍는다. PR 이 없거나 기록 댓글이
                                         실패한 작업의 보고가 가리킨다
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

TAIL = 40
# 명령마다 받는 옵션. 여기 없는 명령은 옵션을 받지 않는다. --paths 는 뒤에 경로들을 받는다
OPTIONS = {"start": ("--pr-only", "--unattended"), "review": ("--minor", "--spec"), "show": ("--full", "--save"),
           "evidence": ("--paths",), "log": ("--paths",), "tried": ("--paths",), "drop": ("--tried",)}
OPTION = re.compile(r"--\S+")  # 띄어쓰기가 든 글(「--unattended 를 고친다」)은 옵션이 아니다
COMMANDS = re.findall(r"^  job\.py (\S+)", __doc__, re.M)


def usage(cmd):
    """사용법에서 그 명령의 첫 줄."""
    line = re.search(r"^  job\.py %s(?: .*)?$" % re.escape(cmd), __doc__, re.M).group(0)
    return " ".join(line.split())


def git_dir(cwd):
    r = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def state_path(cwd):
    d = git_dir(cwd)
    return os.path.join(d, "fade-job.json") if d else None


def load(cwd):
    p = state_path(cwd)
    if not p or not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(cwd, state):
    # 데스크톱 앱이 만든 워크트리에서 시작한 뒤 레포 규칙대로 브랜치를 새로 따는 일이 있어, 기록할 때마다 지금 브랜치로 맞춘다
    state["branch"] = branch(cwd)
    p = state_path(cwd)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(p + ".tmp", p)


def branch(cwd):
    r = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def head(cwd):
    r = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "(커밋 없음)"


def short(sha):
    return sha[:7] if sha != "(커밋 없음)" else sha


def dirty(cwd):
    # 스크린샷 같은 추적하지 않는 파일은 빼고, 커밋하지 않은 코드 변경만 본다
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd, capture_output=True, text=True)
    return bool(r.stdout.strip())


def run(cwd, command):
    # stderr 를 stdout 에 합쳐 터미널에 찍힌 순서를 지킨다. 실패한 log 는 그 끝만 보이니 원인이 순서째 끝에 있어야 한다
    r = subprocess.run(command, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.returncode, r.stdout


def tail_of(text):
    return "\n".join(text.splitlines()[-TAIL:])


def at(record):
    return short(record["head"]) + (", 커밋 전 변경 있음" if record.get("dirty") else "")


def where(cwd):
    return {"head": head(cwd), "dirty": dirty(cwd)}


def top_dir(cwd):
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    return os.path.realpath(r.stdout.strip())


def is_ancestor(cwd, old, new):
    """old 가 new 의 조상(또는 같은 커밋)인가. rebase 나 amend 로 사라진 커밋, 없는 SHA 는 아니다."""
    r = subprocess.run(["git", "merge-base", "--is-ancestor", old, new], cwd=cwd, capture_output=True, text=True)
    return r.returncode == 0


def parse(cmd, args):
    """옵션 판정은 모든 명령이 여기 한 곳에서 한다. (값 인자, 옵션들, --paths 뒤의 경로 또는 None)을 돌려준다.
    맨 처음 나온 -- 뒤의 인자는 모두 값이다. -- 로 시작하는 한 단어를 제목, 요약, 이유로 넣는 자리다."""
    end = args.index("--") if "--" in args else len(args)
    head, tail = args[:end], args[end + 1:]
    unknown = [a for a in head if OPTION.fullmatch(a) and a not in OPTIONS.get(cmd, ())]
    if unknown:
        sys.exit("모르는 옵션: %s\n%s" % (", ".join(unknown), usage(cmd)))
    paths = None
    if "--paths" in head:
        i = head.index("--paths")
        head, paths = head[:i], head[i + 1:]
        if "--paths" in paths:
            sys.exit("--paths 는 한 번만 쓴다\n" + usage(cmd))
    options = [a for a in head if OPTION.fullmatch(a)]
    return [a for a in head if a not in options] + tail, options, paths


def repo_paths(cwd, paths):
    """--paths 의 경로를 레포 기준으로 바꾼다. 늘 「안 바뀜」으로 읽힐 경로와, 찍는 지금 커밋과 다른 경로는 받지 않는다."""
    if paths is None:
        return []
    if not paths:
        sys.exit("--paths 뒤에 경로가 없다")
    top, out = top_dir(cwd), []
    for p in paths:
        # 링크면 링크 자체와 링크가 가리키는 자리를 둘 다 적는다. 가리키는 곳이 바뀌는 것도, 그곳의 내용이 바뀌는 것도 변경이다
        real = os.path.relpath(os.path.realpath(os.path.join(cwd, p)), top)
        full = os.path.normpath(os.path.join(cwd, p))
        rel = os.path.relpath(os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full)), top)
        if any(r == ".." or r.startswith(".." + os.sep) for r in (real, rel)):
            sys.exit("레포 밖의 경로다: " + p)
        if "." in (rel, real) or not os.path.exists(os.path.join(top, rel)):
            sys.exit("없는 경로다(레포 전체는 받지 않는다): " + p)
        for one in dict.fromkeys((rel, real)):
            tracked = subprocess.run(["git", "ls-files", "--", one], cwd=top, capture_output=True, text=True).stdout
            if not tracked.strip():
                sys.exit("git 이 추적하는 파일이 없는 경로다: " + p + ("" if one == rel else " (링크가 가리키는 %s)" % one))
            out.append(one)
    need_clean(cwd, out)
    return out


def need_clean(cwd, rels):
    """레포 기준 경로들에 커밋 전 변경이나 추적하지 않는 파일이 있으면 받지 않는다. 찍은 내용이 지금 커밋과 달라서다."""
    if not rels:
        return
    changed = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rels], cwd=top_dir(cwd), capture_output=True,
                             text=True).stdout
    if changed.strip():
        sys.exit("그 경로에 커밋 전 변경이나 추적하지 않는 파일이 있다. 커밋한 뒤 찍는다\n" + changed.rstrip())


def holds(cwd, record, now):
    """증거나 써 보기 하나가 지금 커밋에서 유효한가. 지금 커밋에서 찍혔거나, 기대는 경로를 적었고 찍은 커밋이
    지금 커밋의 조상이며 그 뒤로 그 경로가 바뀌지 않았을 때다."""
    if record.get("head") == now:
        return True
    if not record.get("paths") or not is_ancestor(cwd, record["head"], now):
        return False
    r = subprocess.run(["git", "diff", "--quiet", record["head"], now, "--", *record["paths"]], cwd=top_dir(cwd))
    return r.returncode == 0


def brief(text):
    """한 줄로 줄인 글. 여러 줄 명령이 빠진 것 목록의 한 항목이나 기록 명령의 한 줄을 여러 줄로 가르지 않게 한다."""
    text = " ".join(text.split())
    return text if len(text) <= 80 else text[:77] + "..."


def name_of(record):
    """낡은 증거나 써 보기를 가리킬 짧은 이름."""
    return "`%s`" % brief(record.get("what") or record.get("cmd") or ", ".join(os.path.basename(f) for f in record["files"]))


def report_path(cwd):
    """show --save 가 쓰는 파일. 워크트리와 브랜치가 지워져도 남도록 메인 체크아웃의 git 폴더 안에 둔다."""
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                       capture_output=True, text=True)
    return os.path.join(r.stdout.strip(), "fade-job-reports", (branch(cwd) or "HEAD") + ".md")


def put(records, new, same):
    """같은 것을 다시 남기면 앞의 것을 그 자리에서 바꾸고, 아니면 끝에 붙인다."""
    for i, old in enumerate(records):
        if all(old.get(k) == new.get(k) for k in same):
            records[i] = new
            return
    records.append(new)


SOURCES = ("review", "ci", "try", "user")  # slip 이 받는 출처. gate, permission, stop 은 훅과 stop 이 스스로 쓴다
KEY = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def mistakes_path():
    return os.environ.get("FADE_MISTAKES") or os.path.expanduser("~/.claude/fade/mistakes.jsonl")


def under_temp(path):
    """OS 임시 폴더 아래인가. macOS 의 /tmp 와 /var/folders 는 /private 아래를 가리키는 링크라 realpath 로 견준다."""
    real = os.path.realpath(path)
    roots = {os.path.realpath(r) for r in (tempfile.gettempdir(), "/tmp", "/var/folders") if os.path.isdir(r)}
    return any(real == r or real.startswith(r + os.sep) for r in roots)


def mistake_rows():
    path = mistakes_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def mask(text):
    """공개 PR 에도 붙는 글에서 사용자 이름이 든 홈 경로를 줄인다. Claude 가 경로로 만드는 폴더 이름
    (세션 임시 폴더, 세션 기록 폴더)은 영숫자가 아닌 글자를 모두 - 로 바꾼 꼴(-Users-<이름>-)이라 그것도 가린다."""
    home = os.path.expanduser("~")
    dashed = re.sub(r"[^A-Za-z0-9]", "-", home)
    text = text.replace(home, "~")
    return re.sub(re.escape(dashed) + r"(?![A-Za-z0-9])", "-~", text)


def main_checkout(cwd):
    """워크트리는 작업이 끝나면 사라지니, 실수 기록에는 메인 체크아웃 경로를 레포로 남긴다."""
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                       capture_output=True, text=True)
    common = r.stdout.strip()
    return os.path.dirname(common) if r.returncode == 0 and os.path.basename(common) == ".git" else common


def add_mistake(cwd, state, source, what, key=""):
    """실수 기록에 한 줄을 붙인다. 파일과 폴더가 없으면 만든다. 쓴 파일의 경로를 돌려준다.
    임시 폴더의 레포(테스트, 써 보기)에서 FADE_MISTAKES 를 정하지 않았으면 쓰지 않고 None 을 돌려준다.
    훅도 이 함수로 쓰니 막는 자리가 여기 하나다."""
    repo = main_checkout(cwd)
    if not os.environ.get("FADE_MISTAKES") and under_temp(repo):
        return None
    row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repo": repo, "branch": branch(cwd),
           "pr": state.get("pr") or "", "source": source, "what": what, "key": key, "handled": ""}
    path = mistakes_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def fill_pr(cwd, state):
    """리뷰 slip 과 승인 창 훅의 줄은 PR 을 열기 전에 찍혀 pr 칸이 빈다. 이 작업(같은 레포, 같은 브랜치,
    작업을 시작한 뒤)의 줄 가운데 pr 이 빈 것에 PR 을 채운다. 같은 브랜치 이름을 다시 쓴 예전 작업의 줄은 건드리지 않는다."""
    path, repo, now, since = mistakes_path(), main_checkout(cwd), branch(cwd), int(state.get("started") or 0)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    changed = False
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        row = json.loads(line)
        try:
            at_ = time.mktime(time.strptime(row["time"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError):
            continue
        if row.get("pr") or row.get("repo") != repo or row.get("branch") != now or at_ < since:
            continue
        row["pr"] = state["pr"]
        lines[i] = json.dumps(row, ensure_ascii=False)
        changed = True
    if changed:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(path + ".tmp", path)


def mark(args):
    if len(args) < 3 or args[1] not in ("key", "handled"):
        sys.exit("job.py mark <줄 번호> key|handled <값>")
    path = mistakes_path()
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    if not args[0].isdigit() or not 1 <= int(args[0]) <= len(lines):
        sys.exit("실수 기록에 없는 줄이다: %s (%d줄)" % (args[0], len(lines)))
    n = int(args[0]) - 1
    row = json.loads(lines[n])
    row[args[1]] = args[2]
    lines[n] = json.dumps(row, ensure_ascii=False)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(path + ".tmp", path)
    print("%d: %s" % (n + 1, lines[n]))


def status(state):
    if state["merged"]:
        return "병합됨"
    if state.get("stopped"):
        return "멈춤(%s)" % state["stopped"]
    if state["scope"] == "pr" and state["pr"]:
        return "PR 까지"
    return "진행 중"


def missing(state, cwd):
    """병합을 막는 빠진 것들. 비어 있으면 병합해도 된다. green 과 리뷰는 지금 커밋 것만 치고,
    증거와 써 보기는 하나하나가 holds() 여야 한다. 유효한 것이 낡은 것을 가리지 않는다."""
    now = head(cwd)
    s = short(now)
    out = []
    if state.get("stopped"):
        out.append("멈춤: " + state["stopped"])
    if state["scope"] == "pr":
        out.append("이번 작업은 PR 까지만이다. 병합하지 않는다")
    if not state["no_test"]:
        if not (state["red"] and state["green"]):
            out.append("테스트: 구현 전 실패(red)와 구현 후 통과(green)가 없다. 장치가 없으면 no-test 로 이유를 적는다")
        elif state["green"]["head"] != now or state["green"].get("dirty"):
            out.append("테스트: green 을 마지막 커밋(%s)에서 커밋 전 변경 없이 다시 돌리지 않았다" % s)
    criteria = list(dict.fromkeys(e["criterion"] for e in state["evidence"]))
    if not criteria:
        out.append("증거: 완료 기준에 붙인 로그나 스크린샷이 없다")
    stale = "%s. 찍은 뒤 기대는 경로가 바뀌었거나, 경로를 적지 않았는데 커밋이 바뀌었다. 마지막 커밋(%s)에서 같은 %s 다시 남긴다"
    for c in criteria:
        old = [name_of(e) for e in state["evidence"] if e["criterion"] == c and not holds(cwd, e, now)]
        if old:
            out.append("증거: 「%s」의 낡은 증거 " % c + stale % (", ".join(old), s, "명령이나 파일로"))
    if not state["try_na"] and not state["human"]:
        old = [name_of(t) for t in state["tried"] if not holds(cwd, t, now)]
        if not state["tried"]:
            out.append("직접 써 보기: 기록이 없다. 써 볼 것이 없는 작업이면 try-na, 지금 못 하면 human 으로 남긴다")
        elif old:
            out.append("직접 써 보기: 낡은 기록 " + stale % (", ".join(old), s, "글로") + ". 더 하지 않을 것은 drop --tried 로 지운다")
    door = state.get("door")
    if not door:
        out.append("되돌릴 수 있는가: 기록이 없다. job.py door one-way|two-way \"<이유와 영향 범위>\" 로 남긴다")
    elif door["kind"] == "one-way":
        out.append("한쪽 문(되돌릴 수 없음): %s. 병합은 사용자가 정한다" % door["why"])
    review = state.get("review")
    if not review:
        out.append("리뷰: 기록이 없다. 코드 리뷰를 돌리고 job.py review <남은 막는 지적 수> <요약> [--spec] 으로 남긴다")
    elif review["head"] != now or review.get("dirty"):
        out.append("리뷰: 마지막 커밋(%s)에서 커밋 전 변경 없이 다시 하지 않았다" % s)
    elif review["left"]:
        out.append("리뷰: 남은 막는 지적 %d개" % review["left"])
    for h in state["human"]:
        out.append("사람이 볼 것: " + h)
    return out


def file_lines(files):
    out = []
    for f in files:
        out.append("    - " + f)
        if f.endswith(".log") and os.path.isfile(f):
            with open(f, encoding="utf-8", errors="replace") as fh:
                out += ["", "      ```text"] + ["      " + line for line in fh.read().splitlines()] + ["      ```", ""]
    return out


def taken(record):
    """기록 명령의 한 줄에 붙이는, 찍은 커밋과 기대는 경로 수."""
    return "커밋 %s%s" % (at(record), ", 기대는 경로 %d개" % len(record["paths"]) if record.get("paths") else "")


def commits(records):
    return ", ".join(dict.fromkeys(at(r) for r in records if r.get("head"))) or "모름"


def detail(record):
    """--full 에서 증거나 써 보기 하나에 붙이는 괄호들."""
    return ((" (명령 `%s`, 종료 코드 %d)" % (record["cmd"], record["code"]) if record.get("cmd") else "")
            + (" (커밋 %s)" % at(record) if record.get("head") else "")
            + (" (기대는 경로 %s)" % ", ".join(record["paths"]) if record.get("paths") else ""))


def open_questions(state):
    return [q for q in state.get("questions", []) if q["answer"] is None]  # start 가 이 칸을 넣기 전에 시작한 기록에는 없다


def show(state, cwd, full=False):
    questions = state.get("questions", [])
    open_ = ["%d. %s" % (q["id"], q["question"]) for q in open_questions(state)]
    lines = ["상태: " + status(state)]
    if open_:
        lines += ["답을 받지 못한 질문 (보고의 첫 줄인 기록 주소 다음에 번호째 다시 적는다):"] + open_
    lines += ["", "## 작업 기록 (fade job)", "", "- 작업: " + state["title"],
              "- 범위: " + ("PR 까지" if state["scope"] == "pr" else "병합까지")]
    for q in questions:
        if q["answer"] is not None:
            lines.append("- 물은 것: %d. %s → %s" % (q["id"], q["question"], q["answer"]))
    if state.get("unattended"):
        lines.append("- 사람 없음: 승인 창이 뜨면 기다리지 않고 거부된다")
    if state.get("stopped"):
        lines.append("- 멈춤: " + state["stopped"])
    if state["no_test"]:
        lines.append("- 테스트: 없음 — " + state["no_test"])
    for old in state.get("red_history", []):
        lines.append("- 앞서 기록한 실패(red, %s): `%s` → 종료 코드 %d" % (at(old), old["cmd"], old["code"]))
    if state["red"]:
        lines.append("- 구현 전 실패(red, %s): `%s` → 종료 코드 %d" % (at(state["red"]), state["red"]["cmd"], state["red"]["code"]))
    if state["green"]:
        lines.append("- 구현 후 통과(green, %s): `%s`" % (at(state["green"]), state["red"]["cmd"]))
    if state["evidence"]:
        lines.append("- 증거:")
        for e in state["evidence"] if full else []:
            lines.append("  - " + e["criterion"] + detail(e))
            lines += file_lines(e["files"])
        for c in [] if full else dict.fromkeys(e["criterion"] for e in state["evidence"]):
            group = [e for e in state["evidence"] if e["criterion"] == c]
            codes = ", ".join(str(e["code"]) for e in group if e.get("cmd"))
            lines.append("  - %s (증거 %d개%s, 커밋 %s)" % (c, len(group), ", 종료 코드 " + codes if codes else "", commits(group)))
    if state["tried"]:
        lines.append("- 직접 써 보기:")
        for t in state["tried"]:
            lines.append("  - " + t["what"] + (detail(t) if full else " (커밋 %s)" % commits([t])))
            lines += file_lines(t["files"]) if full else []
    if state["try_na"]:
        lines.append("- 직접 써 보기: 해당 없음 — " + state["try_na"])
    for h in state["human"]:
        lines.append("- 사람이 볼 것: " + h)
    door = state.get("door")
    if door:
        lines.append("- 되돌릴 수 있는가: %s — %s" % ("한쪽 문" if door["kind"] == "one-way" else "양쪽 문", door["why"]))
    review = state.get("review")
    if review:
        lines.append("- 리뷰(%s%s): 남은 막는 지적 %d개%s" % (
            at(review), ", 사소한 지적을 모아 고친 커밋의 버그 축" if review.get("minor") else
            ", 명세 리뷰어도 봄" if review.get("spec") else "", review["left"],
            " — " + review["note"] if review["note"] else ""))
    if state["pr"]:
        lines.append("- PR: " + state["pr"])
    if state["merged"]:
        lines.append("- 병합: " + state["merged"]["commit"] + (" · " + state["merged"]["ci"] if state["merged"]["ci"] else ""))
    return mask("\n".join(lines))


def review_files(cwd, state, base):
    """리뷰어는 읽기 도구만 있어 작업 폴더 밖을 읽으려면 승인이 필요하고, 데스크톱 앱은 파일 도구로 git 폴더에
    쓰는 것을 막는다. 그래서 워크트리 안에 두되, 안의 .gitignore 가 폴더째 git 에서 빼게 한다.
    명세 리뷰어를 띄울지는 정하지 않는다. 부르는 쪽이 판단하도록 크기와 바뀐 파일만 알린다."""
    stat = subprocess.run(["git", "diff", "--numstat", base + "...HEAD"], cwd=cwd, capture_output=True, text=True)
    if stat.returncode != 0:
        sys.exit("base 와의 diff 를 만들지 못했다: " + stat.stderr.strip())
    rows = [row.split("\t", 2) for row in stat.stdout.splitlines()]
    # 바이너리 파일은 줄 수가 - 로 나온다. 세지 않는다
    added, removed = (sum(int(row[i]) for row in rows if row[i].isdigit()) for i in (0, 1))
    now, review = head(cwd), state.get("review") or {}
    # 고친 부분만 주는 것은 명세 리뷰어가 실제로 본 커밋이 남아 있는 경우뿐이다
    since = review.get("spec_head")
    since = since if since and is_ancestor(cwd, since, now) else None
    r = subprocess.run(["git", "diff", since, "HEAD"] if since else ["git", "diff", base + "...HEAD"], cwd=cwd,
                       capture_output=True, text=True)
    folder = os.path.join(top_dir(cwd), ".fade-review")
    os.makedirs(folder, exist_ok=True)
    for name, text in ((".gitignore", "*\n"), ("show.txt", show(state, cwd) + "\n"), ("diff.patch", r.stdout)):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    state["review_files"] = {"head": now, "dirty": dirty(cwd)}
    print("base 와의 diff: 파일 %d개, 더한 줄 %d + 뺀 줄 %d = %d줄" % (len(rows), added, removed, added + removed))
    print("diff.patch: " + ("고친 부분만(명세 리뷰어가 본 %s 뒤의 diff)" % short(since) if since else "전체(base 와의 diff)"))
    print("\n".join(stat.stdout.splitlines()))
    return folder


def minor_spec_head(cwd, prev, now):
    """review --minor 를 받을 수 있으면 명세 리뷰어가 마지막으로 본 커밋(없으면 None)을 돌려주고, 아니면 이유를 내며 끝낸다.
    명세 리뷰어는 사소한 지적을 고친 커밋을 보지 않으니 앞 리뷰의 값을 그대로 넘긴다."""
    back = "원래 흐름대로 review-files 부터 다시 리뷰한다"
    if not prev or prev["left"] or prev.get("dirty"):
        sys.exit("--minor 는 앞 리뷰에서 커밋 전 변경 없이 남은 막는 지적이 0 이 된 뒤에만 쓴다. " + back)
    if prev.get("minor"):
        sys.exit("앞 리뷰가 이미 사소한 지적을 모아 고친 커밋의 리뷰다. 사소한 지적은 한 번에 모아 고친다. " + back)
    if not is_ancestor(cwd, prev["head"], now):
        sys.exit("앞 리뷰의 커밋(%s)이 사라졌다. %s" % (short(prev["head"]), back))
    count = subprocess.run(["git", "rev-list", "--count", prev["head"] + ".." + now], cwd=cwd, capture_output=True,
                           text=True).stdout.strip()
    if count != "1":
        sys.exit("앞 리뷰(%s) 뒤의 커밋이 하나가 아니다(%s개). 사소한 지적은 한 커밋으로 고친다. %s"
                 % (short(prev["head"]), count, back))
    return prev.get("spec_head")


def need_files(cwd, paths):
    if not paths:
        sys.exit("파일이 하나도 없다. 화면이면 스크린샷, 명령이면 출력 파일의 경로를 준다")
    mine = [top_dir(cwd), os.path.realpath(git_dir(cwd))]
    for p in paths:
        if not os.path.isfile(p):
            sys.exit("없는 파일: " + p)
        real = os.path.realpath(p)
        # 세션 임시 폴더는 지워질 수 있고 경로에 사용자 이름이 든다. 레포 자신이 임시 폴더에 있으면(테스트) 그 안은 받는다
        if under_temp(real) and not any(real.startswith(m + os.sep) for m in mine):
            sys.exit("레포 밖 임시 폴더의 파일이다(지워질 수 있다): %s\n`$(git rev-parse --absolute-git-dir)/fade-try/` "
                     "아래로 옮겨 붙인다" % p)
    return [os.path.abspath(p) for p in paths]


NOT_WRITTEN = "임시 폴더의 레포라 실수 기록에 쓰지 않았다(FADE_MISTAKES 를 정하면 쓴다)"


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    cmd, cwd = argv[1], os.getcwd()
    if cmd not in COMMANDS:
        sys.exit(__doc__)
    args, options, paths = parse(cmd, argv[2:])
    if cmd == "mark":
        mark(args)
        return
    if not git_dir(cwd):
        sys.exit("git 레포 안에서 돌린다")
    state = load(cwd)
    if cmd == "start":
        if state and not state["merged"] and state.get("branch") == branch(cwd):
            sys.exit("이 브랜치에는 이미 시작한 작업이 있다: " + state["title"])
        if len(args) != 1 or not args[0].strip():
            sys.exit("작업 제목은 하나다\n" + usage("start"))
        state = {"title": args[0], "scope": "pr" if "--pr-only" in options else "merge", "started": time.time(),
                 "branch": branch(cwd), "unattended": "--unattended" in options,
                 "red": None, "green": None, "no_test": None, "evidence": [], "tried": [], "try_na": None,
                 "human": [], "questions": [], "review": None, "door": None, "stopped": None, "pr": None, "merged": None}
        save(cwd, state)
        print("작업을 시작했다: 「%s」 (범위: %s%s)" % (brief(args[0]), "PR 까지" if state["scope"] == "pr" else "병합까지",
                                                   ", 사람 없음" if state["unattended"] else ""))
        print("기록 전체는 `job.py show`, 병합 조건에서 빠진 것은 `job.py check` 로 본다")
        return
    if state is None:
        sys.exit("작업 기록이 없다. job.py start 부터 한다")
    need = {"scope": 1, "red": 1, "no-test": 1, "evidence": 2, "log": 2, "tried": 1, "try-na": 1, "human": 1,
            "review": 1, "review-files": 1, "door": 2, "ask": 1, "answered": 2, "stop": 1, "slip": 1, "pr": 1, "merged": 1}
    if len(args) < need.get(cmd, 0):
        sys.exit(usage(cmd))
    if cmd == "show":
        if "--save" in options:
            path = report_path(cwd)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(show(state, cwd, full=True) + "\n")
            print("기록 전문을 썼다: " + path)
        else:
            print(show(state, cwd, full="--full" in options))
        return
    # 기록 명령은 무엇을 기록했는지(said)만 찍는다. 기록 전체는 show, 빠진 것은 check 가 낸다
    if cmd == "scope":
        if args[0] not in ("merge", "pr"):
            sys.exit("범위는 merge 나 pr 이다")
        state["scope"] = args[0]
        said = "범위를 바꿨다: " + ("PR 까지" if args[0] == "pr" else "병합까지")
    elif cmd == "red":
        code, out = run(cwd, args[0])
        if code == 0:
            sys.exit("테스트가 실패하지 않는다. 이번 변경을 판정하지 못하는 테스트다. 테스트를 고친다\n" + tail_of(out))
        if state["red"]:
            state.setdefault("red_history", []).append(state["red"])
        state["red"] = {"cmd": args[0], "code": code, "head": head(cwd), "dirty": dirty(cwd), "tail": tail_of(out)}
        state["green"] = None
        said = "red 를 기록했다: %s → 종료 코드 %d (커밋 %s)" % (name_of(state["red"]), code, at(state["red"]))
    elif cmd == "green":
        if not state["red"]:
            sys.exit("red 가 없다. 구현 전에 실패하는 테스트부터 기록한다")
        code, out = run(cwd, state["red"]["cmd"])
        if code != 0:
            sys.exit("테스트가 아직 통과하지 않는다 (종료 코드 %d)\n%s" % (code, tail_of(out)))
        state["green"] = {"head": head(cwd), "dirty": dirty(cwd), "tail": tail_of(out)}
        said = "green 을 기록했다: %s 통과 (커밋 %s)" % (name_of(state["red"]), at(state["green"]))
    elif cmd == "no-test":
        state["no_test"] = args[0]
        said = "테스트 없음을 기록했다: " + brief(args[0])
    elif cmd == "evidence":
        record = {"criterion": args[0], "files": need_files(cwd, args[1:]), "paths": repo_paths(cwd, paths), **where(cwd)}
        put(state["evidence"], record, ("criterion", "files"))
        said = "증거를 기록했다: 「%s」 ← 파일 %d개 (%s)" % (brief(args[0]), len(record["files"]), taken(record))
    elif cmd == "drop":
        if len(args) != ("--tried" not in options):
            sys.exit(usage("drop"))
        if "--tried" in options:
            said = "지웠다: 써 보기 %d개" % len(state["tried"])
            state["tried"] = []
        else:
            kept = [e for e in state["evidence"] if e["criterion"] != args[0]]
            if len(kept) == len(state["evidence"]):
                sys.exit("그 기준에 붙인 증거가 없다: " + args[0])
            said = "지웠다: 「%s」의 증거 %d개" % (brief(args[0]), len(state["evidence"]) - len(kept))
            state["evidence"] = kept
    elif cmd == "log":
        paths = repo_paths(cwd, paths)
        code, out = run(cwd, args[1])
        need_clean(cwd, paths)  # 명령이 그 경로를 고쳤으면 지금 커밋의 내용으로 찍힌 증거가 아니다
        logs = os.path.join(git_dir(cwd), "fade-job-logs")
        os.makedirs(logs, exist_ok=True)
        path = os.path.join(logs, "%02d.log" % (len([f for f in os.listdir(logs) if f.endswith(".log")]) + 1))
        with open(path, "w", encoding="utf-8") as f:
            f.write("$ %s\n%s\n(종료 코드 %d)\n" % (args[1], out.rstrip("\n"), code))
        record = {"criterion": args[0], "files": [path], "cmd": args[1], "code": code, "paths": paths, **where(cwd)}
        put(state["evidence"], record, ("criterion", "cmd"))
        said = "증거를 기록했다: 「%s」 ← %s → 종료 코드 %d (%s, 로그 %s)" % (brief(args[0]), name_of(record), code,
                                                                  taken(record), path)
        if code:  # 실패한 명령은 원인을 알 만큼 끝을 보인다. 성공한 명령의 출력은 로그 파일에만 둔다
            said += ("\n종료 코드가 0 이 아니라 출력 끝(%d줄까지)을 붙인다. 전체는 로그 파일에 있다:\n%s" % (TAIL, tail_of(out))
                     if out.strip() else "\n종료 코드가 0 이 아니고, 명령이 아무것도 찍지 않았다")
    elif cmd == "tried":
        record = {"what": args[0], "files": need_files(cwd, args[1:]), "paths": repo_paths(cwd, paths), **where(cwd)}
        put(state["tried"], record, ("what",))
        said = "써 보기를 기록했다: %s (파일 %d개, %s)" % (name_of(record), len(record["files"]), taken(record))
    elif cmd == "try-na":
        state["try_na"] = args[0]
        said = "써 보기 해당 없음을 기록했다: " + brief(args[0])
    elif cmd == "human":
        state["human"].append(args[0])
        said = "사람이 볼 것을 기록했다: %s. 남아 있으면 병합하지 않는다" % brief(args[0])
    elif cmd == "review":
        if not args[0].isdigit():
            sys.exit("남은 막는 지적 수는 0 이상의 정수다")
        made, minor, spec, now = state.get("review_files") or {}, "--minor" in options, "--spec" in options, head(cwd)
        note, prev = " ".join(args[1:2]), state.get("review") or {}
        if minor and spec:
            sys.exit("--spec 과 --minor 는 함께 쓰지 않는다. 사소한 지적을 고친 커밋은 명세 리뷰어를 다시 띄우지 않는다")
        if minor:
            spec_head = minor_spec_head(cwd, state.get("review"), now)
        elif spec:
            # 명세 리뷰어가 이 커밋까지 봤는가: 리뷰 입력을 이 커밋에서 만들었고, 그 뒤 작업 트리도 바뀌지 않았다
            if made.get("head") != now or made.get("dirty") or dirty(cwd):
                sys.exit("명세 리뷰어에게 준 입력이 이 커밋(%s)에서 커밋 전 변경 없이 만든 것이 아니다. "
                         "review-files 부터 다시 만들어 명세 리뷰어를 띄운다" % short(now))
            spec_head = now
        else:
            if not note.strip():
                sys.exit("명세 리뷰어를 띄우지 않았으면 띄우지 않은 이유를 요약에 적는다. 띄웠으면 --spec 을 붙인다\n"
                         + usage("review"))
            spec_head = prev.get("spec_head")  # 명세 리뷰어가 마지막으로 본 커밋은 그대로다
        # spec_head 는 명세 리뷰어가 마지막으로 본 커밋이다. 다음 review-files 가 그 뒤의 diff 만 준다
        state["review"] = {"left": int(args[0]), "note": note, "spec_head": spec_head, "minor": minor, "spec": spec,
                           **where(cwd)}
        said = "리뷰를 기록했다: 남은 막는 지적 %d개 (커밋 %s%s)" % (
            int(args[0]), at(state["review"]), ", 사소한 지적을 모아 고친 커밋의 버그 축" if minor else
            ", 명세 리뷰어도 봄" if spec else "")
    elif cmd == "door":
        if args[0] not in ("one-way", "two-way") or not args[1].strip():
            sys.exit("job.py door one-way|two-way \"<이유와 영향 범위>\"")
        state["door"] = {"kind": args[0], "why": args[1]}
        said = "되돌릴 수 있는가를 기록했다: " + ("한쪽 문. 병합은 사용자가 정한다" if args[0] == "one-way" else "양쪽 문")
    elif cmd == "ask":
        if not args[0].strip():
            sys.exit("질문이 비었다\n" + usage("ask"))
        questions = state.setdefault("questions", [])
        questions.append({"id": len(questions) + 1, "question": args[0], "answer": None})
        said = "질문 %d번을 남겼다. 답을 받으면 job.py answered %d \"<답>\" 으로 적는다" % (len(questions), len(questions))
    elif cmd == "answered":
        questions = state.get("questions", [])
        if not args[0].isdigit() or not 1 <= int(args[0]) <= len(questions):
            sys.exit("기록에 없는 질문 번호다: %s (%d개)" % (args[0], len(questions)))
        if not args[1].strip():
            sys.exit("답이 비었다\n" + usage("answered"))
        questions[int(args[0]) - 1]["answer"] = args[1]
        said = "질문 %d번의 답을 적었다" % int(args[0])
    elif cmd == "stop":
        state["stopped"] = args[0]
        save(cwd, state)
        written = add_mistake(cwd, state, "stop", args[0])
        said = "멈춤을 기록했다: %s. 병합을 막고 %s" % (brief(args[0]), "실수 기록에 남겼다" if written else NOT_WRITTEN)
    elif cmd == "slip":
        keys = list(dict.fromkeys(r["key"] for r in reversed(mistake_rows()) if r.get("key")))
        if args[0] not in SOURCES or len(args) != 3 or not KEY.fullmatch(args[1]) or not args[2].strip():
            sys.exit("job.py slip %s <key> \"<무엇을 잘못했나>\". key 는 같은 실수끼리 묶는 이름(영문 소문자, 숫자, -)이고, "
                     "같은 실수의 key 가 있으면 그것을 쓴다. 병합 훅·승인 창 훅·stop 은 스스로 남긴다\n있는 key: %s"
                     % ("|".join(SOURCES), ", ".join(keys[:30]) or "없음"))
        source, key, what = args
        written = add_mistake(cwd, state, source, what, key)
        state.setdefault("slips", []).append({"source": source, "key": key, "what": what, **where(cwd)})
        nth = sum(1 for r in mistake_rows() if r.get("key") == key) if written else 0
        said = "%s(%s, key %s%s): %s" % ("실수 기록에 남겼다" if written else NOT_WRITTEN, source, key,
                                       ", 이 key 의 %d번째" % nth if nth else "", brief(what))
    elif cmd == "pr":
        state["pr"] = args[0]
        fill_pr(cwd, state)
        said = "PR 을 기록했다: " + args[0]
    elif cmd == "merged":
        state["merged"] = {"commit": args[0], "ci": args[1] if len(args) > 1 else ""}
        said = "병합을 기록했다: " + args[0] + (" · " + args[1] if len(args) > 1 else "")
    elif cmd == "review-files":
        folder = review_files(cwd, state, args[0])
        save(cwd, state)
        print("%s 에 show.txt, diff.patch 를 썼다. 계획서 원문을 %s 로 쓰고 세 경로를 리뷰어에게 준다"
              % (folder, os.path.join(folder, "plan.md")))
        return
    elif cmd == "check":
        left = missing(state, cwd)
        print("\n".join("- " + m for m in left) if left else "병합 조건을 모두 채웠다")
        sys.exit(1 if left else 0)
    else:
        sys.exit(__doc__)
    save(cwd, state)
    print(said)
    left = open_questions(state)
    if left:  # 기록 명령만 부르다 보고에서 빠뜨리지 않게, 답 없는 질문이 있다는 것은 늘 알린다
        print("답을 받지 못한 질문 %d개(%s번)가 있다. 보고의 첫 줄인 기록 주소 다음에 번호째 다시 적는다(글은 job.py show)"
              % (len(left), ", ".join(str(q["id"]) for q in left)))


if __name__ == "__main__":
    main(sys.argv)
