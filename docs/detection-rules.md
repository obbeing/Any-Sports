# 탐지 규칙 (Any-Sports 탐지기)

탐지기는 10초마다 Elasticsearch에서 최근 로그를 조회해 아래 규칙을 적용한다.
임계값은 `scripts/detector.py` 의 `CFG` 에서 바꾼다.

| 규칙 | 조건 | 조치 | 로그 출처 |
|---|---|---|---|
| injection_probe | 5분 내 같은 IP에서 이상 검색어(UNION SELECT, `OR 1=1`, `<script`, `../`, `;DROP` 등) 3회 이상 | IP 30분 차단 | Nginx |
| bot_ua | 5분 내 같은 IP에서 봇 User-Agent(python-requests, curl 등) 요청 10회 이상 | IP 30분 차단 | Nginx |
| login_bruteforce | 5분 내 같은 IP에서 로그인 실패 10회 이상 | IP 30분 차단 | 앱 이벤트 |
| comment_spam | 10분 내 같은 IP에서 금칙어 댓글(격리됨) 3회 이상 | IP 30분 차단 | 앱 이벤트 |
| keyword_flood | 1분 내 같은 키워드 15회 이상, 서로 다른 IP가 5~20개이고 IP당 평균 1.5회 이상 | 경보만 (차단 없음) | Nginx |

## 설계 메모
- keyword_flood는 IP가 너무 많으면(20개 초과) 자연스러운 인기 급상승으로 보고 제외한다. 여러 IP가 같은 키워드를 반복 검색하는 패턴만 조작 의심으로 본다.
- 같은 (규칙, IP)는 차단 시간(30분) 동안 다시 보고하지 않는다. 경보는 10분 간격.
- 차단은 `blocklist.json`(공유 볼륨)에 기록되고, 웹 앱이 매 요청마다 읽어 403으로 응답한다. 만료되면 자동 해제된다.
- 탐지 이벤트는 `detector.json.log` → Filebeat → `any-sports-detector-*` 인덱스로 수집되어 Kibana에서 볼 수 있다. `detect_delay_s`는 임계값을 채운 시점부터 탐지까지 걸린 시간이다.

## 한계
- 로그 조회 방식이라 실시간 차단이 아니다 (조회 주기 + Filebeat 지연만큼 늦다).
- IP는 X-Forwarded-For 첫 값을 쓴다. 클라이언트가 조작할 수 있어 실습용 가정이다.
- 오탐 가능성: 한 공유기 뒤의 여러 사용자가 같은 IP로 보이면 로그인 실패가 합산된다.
- 임계값은 테스트 트래픽 기준으로 정한 값이며 실제 서비스에서는 조정이 필요하다.
