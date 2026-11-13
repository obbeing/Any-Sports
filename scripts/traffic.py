#!/usr/bin/env python3
"""Any-Sports 테스트 트래픽 생성기.

내 로컬 테스트 환경(Docker Compose의 nginx)에만 요청을 보낸다.
출발 IP는 X-Forwarded-For 헤더로 흉내 낸 가짜 IP이며,
공개 문서용 예약 대역(192.0.2.x, 198.51.100.x, 203.0.113.x)과 사설 대역(10.x)만 쓴다.

실행 결과는 docs/traffic-truth.jsonl 에 한 줄씩 기록된다 (탐지 정확도 계산용 정답지).
"""
import argparse
import http.cookiejar
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

BASE_URL = os.environ.get("BASE_URL", "http://nginx").rstrip("/")
TRUTH_FILE = os.environ.get("TRUTH_FILE", "/docs/traffic-truth.jsonl")
ALLOWED_HOSTS = {"nginx", "localhost", "127.0.0.1"}  # 내 테스트 환경 밖으로는 보내지 않는다

KEYWORDS = ["서울", "부산", "인천", "대전", "대구", "광주", "울산", "수원",
            "김민준", "이도윤", "박서준", "최하준", "정우진", "강시우",
            "축구", "야구", "농구"]
WEIGHTS = [20, 16, 6, 4, 6, 5, 5, 3, 14, 5, 7, 3, 6, 3, 18, 12, 10]

NORMAL_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
]
BOT_UA = "python-requests/2.31.0"

# 이상 요청 예시 문자열 (파라미터 바인딩을 쓰는 내 사이트에는 동작하지 않는다)
INJECTION_PAYLOADS = [
    "' OR 1=1 --", "\" OR \"1\"=\"1", "<script>alert(1)</script>",
    "../../etc/passwd", "'; DROP TABLE users; --", "1 UNION SELECT 1,2,3",
]
ATTACKER_IPS = ["203.0.113.10", "203.0.113.11"]       # 예약 대역
BRUTE_IP = "198.51.100.23"
BOT_IP = "192.0.2.77"
SPAM_IP = "198.51.100.88"

NORMAL_COMMENTS = ["오늘 경기 재밌었어요", "다음 경기도 기대돼요", "선수들 수고했어요",
                   "응원합니다 화이팅", "결과가 아쉽지만 잘 싸웠어요"]
BANNED_COMMENTS = ["오늘 토토 사이트 추천해요", "안전한 카지노 놀이터 확인하세요",
                   "도 박 사이트 정보 공유합니다", "불법대출 상담 환영해요"]

stats = Counter()


def check_target():
    host = urllib.parse.urlparse(BASE_URL).hostname
    if host not in ALLOWED_HOSTS:
        sys.exit(f"[중단] 대상 '{host}' 는 허용된 테스트 환경이 아닙니다. (허용: {sorted(ALLOWED_HOSTS)})")


def normal_ip():
    return f"10.20.{random.randint(0, 255)}.{random.randint(1, 254)}"


def send(path, method="GET", form=None, ip=None, ua=None, opener=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(BASE_URL + path, data=data, method=method)
    req.add_header("User-Agent", ua or random.choice(NORMAL_UA))
    if ip:
        req.add_header("X-Forwarded-For", ip)
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=10) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except urllib.error.URLError as e:
        sys.exit(f"[오류] 접속 실패: {e.reason} (컨테이너가 떠 있는지 docker ps 로 확인하세요)")


def pause(delay, fixed=False):
    time.sleep(delay if fixed else random.uniform(0, 2 * delay))


def search(q, **kw):
    return send("/search?q=" + urllib.parse.quote(q), **kw)


# ---------- 시나리오 ----------
def normal(count, delay, trend=None, **_):
    for i in range(count):
        w = list(WEIGHTS)
        if trend and trend in KEYWORDS and i >= count // 2:
            w[KEYWORDS.index(trend)] *= 8          # 후반부에 특정 키워드 급상승
        ip = normal_ip()
        if random.random() < 0.7:
            search(random.choices(KEYWORDS, w)[0], ip=ip)
            stats["normal_search"] += 1
        else:
            send(f"/game/{random.randint(1, 6)}", ip=ip)
            stats["normal_view"] += 1
        pause(delay)


def injection(count, delay, **_):
    for _i in range(count):
        search(random.choice(INJECTION_PAYLOADS), ip=random.choice(ATTACKER_IPS))
        stats["injection"] += 1
        pause(delay)


def bruteforce(count, delay, target_user="test_victim", **_):
    for i in range(count):
        send("/login", "POST", {"username": target_user, "password": f"wrong{i}"}, ip=BRUTE_IP)
        stats["login_fail_attempt"] += 1
        pause(delay)


def bot(count, delay, **_):
    """같은 IP, 봇 User-Agent, 일정한 간격으로 반복 요청."""
    for i in range(count):
        search(KEYWORDS[i % 3], ip=BOT_IP, ua=BOT_UA)
        stats["bot_request"] += 1
        pause(delay, fixed=True)


def keyword_flood(count, delay, keyword="서울", **_):
    """여러 IP가 같은 키워드를 짧은 시간에 집중 검색 (검색어 조작 흉내)."""
    ips = [f"198.51.100.{n}" for n in range(100, 110)]
    for i in range(count):
        search(keyword, ip=ips[i % len(ips)])
        stats["keyword_flood"] += 1
        pause(delay)


def spam(count, delay, banned_ratio=0.5, **_):
    """가입 후 로그인해서 정상/금칙어 댓글을 섞어 등록한다."""
    user = f"spam_{random.randint(1000, 9999)}"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    send("/register", "POST", {"username": user, "password": "testpass1"}, ip=SPAM_IP, opener=opener)
    send("/login", "POST", {"username": user, "password": "testpass1"}, ip=SPAM_IP, opener=opener)
    for _i in range(count):
        banned = random.random() < banned_ratio
        text = random.choice(BANNED_COMMENTS if banned else NORMAL_COMMENTS)
        send(f"/game/{random.randint(1, 6)}/comment", "POST", {"content": text}, ip=SPAM_IP, opener=opener)
        stats["comment_banned" if banned else "comment_normal"] += 1
        pause(delay)


def mixed(count, delay, trend=None, **_):
    """정상 90% + 이상 10% (탐지 규칙 시연용)."""
    for i in range(count):
        r = random.random()
        if r < 0.90:
            normal(1, 0, trend=trend if i >= count // 2 else None)  # 후반부에만 급상승
        elif r < 0.94:
            injection(1, 0)
        elif r < 0.97:
            bot(1, 0)
        else:
            keyword_flood(1, 0)
        pause(delay)


SCENARIOS = {
    "normal": normal, "injection": injection, "bruteforce": bruteforce,
    "bot": bot, "keyword_flood": keyword_flood, "spam": spam, "mixed": mixed,
}


def main():
    ap = argparse.ArgumentParser(description="Any-Sports 테스트 트래픽 생성기")
    ap.add_argument("--scenario", choices=SCENARIOS, required=True)
    ap.add_argument("--count", type=int, default=100, help="요청 수 (기본 100)")
    ap.add_argument("--delay", type=float, default=0.1, help="요청 간 평균 대기(초)")
    ap.add_argument("--trend", help="normal/mixed: 후반부에 급상승시킬 키워드")
    ap.add_argument("--keyword", default="서울", help="keyword_flood: 집중 검색할 키워드")
    ap.add_argument("--target-user", default="test_victim", help="bruteforce: 시도할 아이디")
    ap.add_argument("--banned-ratio", type=float, default=0.5, help="spam: 금칙어 댓글 비율")
    a = ap.parse_args()

    check_target()
    started = datetime.now(timezone.utc)
    print(f"[시작] scenario={a.scenario} count={a.count} target={BASE_URL}")
    SCENARIOS[a.scenario](a.count, a.delay, trend=a.trend, keyword=a.keyword,
                          target_user=a.target_user, banned_ratio=a.banned_ratio)
    ended = datetime.now(timezone.utc)

    record = {
        "scenario": a.scenario, "count": a.count, "stats": dict(stats),
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ended.isoformat(timespec="seconds"),
    }
    try:
        os.makedirs(os.path.dirname(TRUTH_FILE), exist_ok=True)
        with open(TRUTH_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[경고] 정답지 기록 실패: {e}")

    print("[완료]", json.dumps(dict(stats), ensure_ascii=False))
    print(f"       {record['started_at']} ~ {record['ended_at']} (UTC)")


if __name__ == "__main__":
    main()
