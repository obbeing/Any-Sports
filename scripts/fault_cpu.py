#!/usr/bin/env python3
"""장애 재현용 CPU 부하 생성기 (로컬 테스트 환경 전용).

지정한 시간 동안 워커 프로세스들이 CPU를 계속 사용한다.
우선순위를 낮춰(nice) 다른 작업이 완전히 멈추지 않도록 한다.
"""
import argparse
import multiprocessing as mp
import os
import time
from datetime import datetime, timezone


def burn(stop_at):
    try:
        os.nice(10)
    except OSError:
        pass
    x = 0
    while time.time() < stop_at:
        x = (x * 31 + 7) % 1000003


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(description="CPU 부하 생성기")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2, help="부하 프로세스 수 (기본: CPU 코어 수)")
    ap.add_argument("--seconds", type=int, default=480, help="부하 지속 시간(초). Zabbix 기본 경보는 5분 이상 90%% 초과")
    a = ap.parse_args()

    stop_at = time.time() + a.seconds
    print(f"[시작] {now()} workers={a.workers} seconds={a.seconds}", flush=True)
    procs = [mp.Process(target=burn, args=(stop_at,)) for _ in range(a.workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    print(f"[종료] {now()}", flush=True)


if __name__ == "__main__":
    main()
