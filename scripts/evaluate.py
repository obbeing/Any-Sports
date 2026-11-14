#!/usr/bin/env python3
"""탐지 결과를 정답지(트래픽 생성기가 쓴 공격 IP)와 비교해 정확도를 계산한다.

사용: docker compose run --rm --no-deps detector python /scripts/evaluate.py [--since 1h]
정답 IP는 scripts/traffic.py 에 정의된 값과 같다. 실행한 시나리오만 --scenarios 로 지정하면 된다.
"""
import argparse
import json
import os
import urllib.request

ES_URL = os.environ.get("ES_URL", "http://elasticsearch:9200").rstrip("/")
TRUTH = {
    "injection": ("injection_probe", {"203.0.113.10", "203.0.113.11"}),
    "bruteforce": ("login_bruteforce", {"198.51.100.23"}),
    "bot": ("bot_ua", {"192.0.2.77"}),
    "spam": ("comment_spam", {"198.51.100.88"}),
    "keyword_flood": ("keyword_flood", {"*"}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="1h", help="조회 구간 (예: 30m, 2h)")
    ap.add_argument("--scenarios", default=",".join(TRUTH), help="실행한 시나리오(쉼표 구분)")
    a = ap.parse_args()

    body = {"size": 1000, "sort": [{"@timestamp": "asc"}],
            "query": {"bool": {"filter": [
                {"term": {"detector.event.keyword": "detected"}},
                {"range": {"@timestamp": {"gte": f"now-{a.since}"}}}]}}}
    req = urllib.request.Request(f"{ES_URL}/any-sports-detector-*/_search", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    hits = [h["_source"]["detector"] for h in json.load(urllib.request.urlopen(req, timeout=15))["hits"]["hits"]]
    detected = {(d["rule"], d["ip"]): d for d in hits}

    chosen = {k: v for k, v in TRUTH.items() if k in a.scenarios.split(",")}
    expected = {(rule, ip) for rule, ips in chosen.values() for ip in ips}
    tp, fn = expected & set(detected), expected - set(detected)
    fp = set(detected) - expected

    print(f"{'규칙':18}{'IP':18}{'결과':8}{'탐지지연(초)'}")
    for key in sorted(expected | set(detected)):
        status = "정탐" if key in tp else ("미탐" if key in fn else "오탐")
        delay = detected.get(key, {}).get("detect_delay_s", "-")
        print(f"{key[0]:18}{key[1]:18}{status:8}{delay}")
    precision = len(tp) / (len(tp) + len(fp)) if tp or fp else 0
    recall = len(tp) / len(expected) if expected else 0
    print(f"\n정탐 {len(tp)} / 미탐 {len(fn)} / 오탐 {len(fp)}  →  정밀도 {precision:.0%}, 재현율 {recall:.0%}")


if __name__ == "__main__":
    main()
