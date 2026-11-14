"""detect() 규칙 단위 테스트. 실행: python scripts/test_detector.py"""
import unittest
from datetime import datetime, timezone

import detector

NOW = datetime(2026, 11, 14, 3, 0, 0, tzinfo=timezone.utc).timestamp()


def stamp(offset):
    return datetime.fromtimestamp(NOW - offset, timezone.utc).isoformat().replace("+00:00", "Z")


def ng(ip, offset, kw=None, ua="Mozilla/5.0"):
    return {"@timestamp": stamp(offset), "nginx": {"client_ip": ip, "search_keyword": kw, "user_agent": ua}}


def ap(ip, offset, event):
    return {"@timestamp": stamp(offset), "app": {"ip": ip, "event": event}}


def rules(found):
    return {(d["rule"], d["ip"]) for d in found}


class DetectTest(unittest.TestCase):
    def test_injection_blocked_at_threshold(self):
        ev = [ng("1.1.1.1", 30 - i, "1 UNION SELECT 1,2,3") for i in range(3)]
        self.assertIn(("injection_probe", "1.1.1.1"), rules(detector.detect(ev, [], NOW)))

    def test_injection_below_threshold(self):
        ev = [ng("1.1.1.1", 30 - i, "' OR 1=1 --") for i in range(2)]
        self.assertEqual(detector.detect(ev, [], NOW), [])

    def test_normal_korean_keywords_not_flagged(self):
        ev = [ng(f"10.0.0.{i}", 10, k) for i, k in enumerate(["서울", "김민준", "축구", "or", "and 야구"] * 5)]
        self.assertFalse([d for d in detector.detect(ev, [], NOW) if d["rule"] == "injection_probe"])

    def test_bot_ua(self):
        ev = [ng("2.2.2.2", 100 - i, "서울", ua="python-requests/2.31.0") for i in range(10)]
        self.assertIn(("bot_ua", "2.2.2.2"), rules(detector.detect(ev, [], NOW)))

    def test_login_bruteforce(self):
        ev = [ap("3.3.3.3", 100 - i, "login_fail") for i in range(10)]
        found = detector.detect([], ev, NOW)
        self.assertEqual([(d["rule"], d["action"]) for d in found], [("login_bruteforce", "block")])

    def test_login_fail_outside_window_ignored(self):
        ev = [ap("3.3.3.3", 400 + i, "login_fail") for i in range(10)]
        self.assertEqual(detector.detect([], ev, NOW), [])

    def test_comment_spam(self):
        ev = [ap("4.4.4.4", 500 - i * 10, "comment_quarantined") for i in range(3)]
        self.assertIn(("comment_spam", "4.4.4.4"), rules(detector.detect([], ev, NOW)))

    def test_keyword_flood_alert_only(self):
        ev = [ng(f"5.5.5.{i % 10}", 50 - i, "서울") for i in range(20)]
        found = [d for d in detector.detect(ev, [], NOW) if d["rule"] == "keyword_flood"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["action"], "alert")

    def test_trending_keyword_from_many_ips_not_flagged(self):
        ev = [ng(f"6.6.{i}.1", 50 - i % 40, "서울") for i in range(60)]   # IP 60개 = 자연스러운 인기 상승
        self.assertFalse([d for d in detector.detect(ev, [], NOW) if d["rule"] == "keyword_flood"])

    def test_trigger_time_is_nth_event(self):
        ev = [ng("1.1.1.1", 60 - i * 10, "../../etc/passwd") for i in range(5)]
        d = detector.detect(ev, [], NOW)[0]
        self.assertEqual(d["trigger_ts"], NOW - 40)   # 3번째 이벤트 시각


if __name__ == "__main__":
    unittest.main()
