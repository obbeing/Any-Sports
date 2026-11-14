#!/usr/bin/env python3
"""Any-Sports 탐지기.

Elasticsearch에 쌓인 로그를 주기적으로 조회해 이상 행위를 찾고,
(1) 탐지 이벤트를 JSON 로그로 남기고 (Filebeat가 다시 ELK로 수집),
(2) IP 차단 목록(blocklist.json)을 갱신하며 (웹 앱이 읽어서 403 처리),
(3) SLACK_WEBHOOK_URL이 설정되어 있으면 알림을 보낸다.

규칙 임계값은 docs/detection-rules.md 에 정리되어 있다.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

ES_URL = os.environ.get("ES_URL", "http://elasticsearch:9200").rstrip("/")
SHARED_DIR = os.environ.get("SHARED_DIR", "/shared")
LOG_FILE = os.environ.get("DETECTOR_LOG", "/logs/detector/detector.json.log")
SLACK_URL = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
BLOCKLIST_FILE = os.path.join(SHARED_DIR, "blocklist.json")

CFG = {
    "window": 300,            # 기본 조회 구간(초)
    "block_minutes": 30,      # 차단 유지 시간
    "alert_cooldown": 600,    # 경보(차단 없음) 재발행 간격(초)
    "login_fail": 10,         # 5분 내 로그인 실패 N회 이상 -> 차단
    "injection": 3,           # 5분 내 이상 검색어 N회 이상 -> 차단
    "bot": 10,                # 5분 내 봇 User-Agent 요청 N회 이상 -> 차단
    "spam_window": 600,       # 스팸 댓글 조회 구간(초)
    "spam": 3,                # 10분 내 격리된 댓글 N회 이상 -> 차단
    "flood_window": 60,       # 검색어 집중 조회 구간(초)
    "flood_count": 15,        # 같은 키워드 N회 이상
    "flood_ips_min": 5,       # 서로 다른 IP 최소 개수
    "flood_ips_max": 20,      # 서로 다른 IP 최대 개수 (넘으면 '인기 급상승'으로 보고 제외)
    "flood_ratio": 1.5,       # IP당 평균 반복 횟수 최소값
}

INJECTION_PATTERNS = [
    re.compile(r"(?i)\bunion\b.+\bselect\b"),
    re.compile(r"(?i)\b(or|and)\b\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+"),
    re.compile(r"(?i)<\s*script"),
    re.compile(r"\.\./"),
    re.compile(r"(?i);\s*(drop|delete|insert|update)\b"),
]
BOT_UA = re.compile(r"(?i)python-requests|curl/|wget|scrapy|httpclient|go-http-client")


# ---------- 유틸 ----------
def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def get(src, path, default=None):
    cur = src
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def is_injection(text):
    return any(p.search(text) for p in INJECTION_PATTERNS)


def emit(level, event, **fields):
    record = {"ts": iso(time.time()), "level": level.upper(), "event": event}
    record.update(fields)
    line = json.dumps(record, ensure_ascii=False)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def notify(text):
    if not SLACK_URL:
        return
    try:
        req = urllib.request.Request(
            SLACK_URL, data=json.dumps({"text": text}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:  # 알림 실패가 탐지를 멈추게 하지 않는다
        emit("warning", "notify_failed", error=str(e)[:100])


# ---------- Elasticsearch ----------
def es_search(index, body):
    req = urllib.request.Request(
        f"{ES_URL}/{index}/_search", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:          # 아직 인덱스가 없는 경우
            return {"hits": {"hits": []}}
        raise


def fetch(index, fields, seconds, extra_filter=None):
    flt = [{"range": {"@timestamp": {"gte": f"now-{int(seconds)}s"}}}]
    if extra_filter:
        flt.append(extra_filter)
    body = {"size": 5000, "sort": [{"@timestamp": "asc"}], "_source": fields,
            "query": {"bool": {"filter": flt}}}
    return [h["_source"] for h in es_search(index, body)["hits"]["hits"]]


# ---------- 차단 목록 ----------
def load_blocklist():
    try:
        with open(BLOCKLIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_blocklist(data):
    os.makedirs(SHARED_DIR, exist_ok=True)
    tmp = BLOCKLIST_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, BLOCKLIST_FILE)


def prune_blocklist(now_ts):
    data = load_blocklist()
    alive = {ip: e for ip, e in data.items() if e.get("until", 0) > now_ts}
    for ip in set(data) - set(alive):
        emit("info", "unblocked", ip=ip, rule=data[ip].get("rule"))
    if alive != data:
        save_blocklist(alive)
    return alive


# ---------- 탐지 규칙 ----------
def nth_time(times, n):
    times = sorted(times)
    return times[n - 1] if len(times) >= n else None


def detect(nginx_events, app_events, now_ts, cfg=CFG):
    """로그 목록을 받아 탐지 결과 목록을 돌려준다 (순수 함수, 테스트하기 쉽게 분리)."""
    found = []
    inj, bot = defaultdict(list), defaultdict(list)
    kw_hits = defaultdict(list)

    for ev in nginx_events:
        ts = parse_ts(ev["@timestamp"])
        ip = get(ev, "nginx.client_ip") or get(ev, "nginx.remote_addr") or "unknown"
        kw = get(ev, "nginx.search_keyword")
        ua = get(ev, "nginx.user_agent") or ""
        if kw and is_injection(kw):
            inj[ip].append((ts, kw))
        if BOT_UA.search(ua):
            bot[ip].append(ts)
        if kw and ts >= now_ts - cfg["flood_window"]:
            kw_hits[kw].append((ts, ip))

    for ip, items in inj.items():
        t = nth_time([x[0] for x in items], cfg["injection"])
        if t:
            found.append(dict(rule="injection_probe", ip=ip, count=len(items), threshold=cfg["injection"],
                              window_s=cfg["window"], action="block", trigger_ts=t,
                              detail="예: " + " | ".join(sorted({x[1] for x in items})[:3])))
    for ip, times in bot.items():
        t = nth_time(times, cfg["bot"])
        if t:
            found.append(dict(rule="bot_ua", ip=ip, count=len(times), threshold=cfg["bot"],
                              window_s=cfg["window"], action="block", trigger_ts=t,
                              detail="봇 User-Agent 반복 요청"))

    for kw, hits in kw_hits.items():
        ips = {h[1] for h in hits}
        if (len(hits) >= cfg["flood_count"] and cfg["flood_ips_min"] <= len(ips) <= cfg["flood_ips_max"]
                and len(hits) / len(ips) >= cfg["flood_ratio"]):
            found.append(dict(rule="keyword_flood", ip="*", count=len(hits), threshold=cfg["flood_count"],
                              window_s=cfg["flood_window"], action="alert",
                              trigger_ts=nth_time([h[0] for h in hits], cfg["flood_count"]),
                              detail=f"키워드 '{kw}' / 서로 다른 IP {len(ips)}개"))

    fails, spam = defaultdict(list), defaultdict(list)
    for ev in app_events:
        ts = parse_ts(ev["@timestamp"])
        ip = get(ev, "app.ip") or "unknown"
        name = get(ev, "app.event")
        if name == "login_fail" and ts >= now_ts - cfg["window"]:
            fails[ip].append(ts)
        elif name == "comment_quarantined" and ts >= now_ts - cfg["spam_window"]:
            spam[ip].append(ts)
    for ip, times in fails.items():
        t = nth_time(times, cfg["login_fail"])
        if t:
            found.append(dict(rule="login_bruteforce", ip=ip, count=len(times), threshold=cfg["login_fail"],
                              window_s=cfg["window"], action="block", trigger_ts=t,
                              detail="로그인 실패 반복"))
    for ip, times in spam.items():
        t = nth_time(times, cfg["spam"])
        if t:
            found.append(dict(rule="comment_spam", ip=ip, count=len(times), threshold=cfg["spam"],
                              window_s=cfg["spam_window"], action="block", trigger_ts=t,
                              detail="금칙어 댓글 반복 등록"))
    return found


def run_once(flagged, now_ts=None, cfg=CFG):
    now_ts = now_ts or time.time()
    blocklist = prune_blocklist(now_ts)
    nginx_events = fetch("any-sports-nginx-*",
                         ["@timestamp", "nginx.client_ip", "nginx.remote_addr", "nginx.search_keyword", "nginx.user_agent"],
                         cfg["window"])
    app_events = fetch("any-sports-app-*", ["@timestamp", "app.event", "app.ip"], cfg["spam_window"],
                       {"terms": {"app.event.keyword": ["login_fail", "comment_quarantined"]}})
    results = []
    for d in detect(nginx_events, app_events, now_ts, cfg):
        key = (d["rule"], d["ip"])
        if flagged.get(key, 0) > now_ts:
            continue                                   # 이미 처리한 건은 쿨다운 동안 건너뜀
        until = now_ts + (cfg["block_minutes"] * 60 if d["action"] == "block" else cfg["alert_cooldown"])
        flagged[key] = until
        delay = round(now_ts - d["trigger_ts"], 1) if d.get("trigger_ts") else None
        extra = {}
        if d["action"] == "block":
            blocklist[d["ip"]] = {"until": until, "rule": d["rule"], "since": iso(now_ts)}
            save_blocklist(blocklist)
            extra["block_until"] = iso(until)
        emit("warning", "detected", rule=d["rule"], ip=d["ip"], count=d["count"], threshold=d["threshold"],
             window_s=d["window_s"], action=d["action"], detail=d["detail"],
             trigger_ts=iso(d["trigger_ts"]) if d.get("trigger_ts") else None, detect_delay_s=delay, **extra)
        notify(f"[Any-Sports 탐지] {d['rule']} ip={d['ip']} count={d['count']} action={d['action']}")
        results.append(d)
    return results


def main():
    ap = argparse.ArgumentParser(description="Any-Sports 탐지기")
    ap.add_argument("--interval", type=int, default=10, help="조회 주기(초)")
    ap.add_argument("--once", action="store_true", help="한 번만 실행하고 종료")
    a = ap.parse_args()

    flagged = {(e["rule"], ip): e["until"] for ip, e in load_blocklist().items() if "rule" in e}
    emit("info", "detector_started", interval=a.interval, es=ES_URL)
    while True:
        try:
            run_once(flagged)
        except (urllib.error.URLError, OSError, ValueError) as e:
            emit("warning", "detector_error", error=str(e)[:200])
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
