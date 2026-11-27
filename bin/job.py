#!/usr/bin/env python3
"""`job.py` 를 경로 없이 부르게 하는 입구. 플러그인이 켜져 있으면 Claude Code 가 이 폴더(bin/)를 Bash 도구의 PATH 에 둔다.
본체는 skills/job/job.py 다. 훅도 그 본체를 읽으니 이 파일에는 아무 동작도 두지 않는다."""
import os
import runpy
import sys

JOB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "job", "job.py")
sys.argv[0] = JOB
runpy.run_path(JOB, run_name="__main__")
