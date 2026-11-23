# Any-Sports

스포츠 점수/스탯/키워드 사이트(3-Tier)와 관제 환경(ELK 로그 분석, 로그 기반 탐지·자동 차단, Zabbix + Grafana 인프라 관제)을 로컬 Docker Compose로 구성한 포트폴리오 프로젝트.

## 구조
Nginx → Flask/Gunicorn → MariaDB
로그: Nginx/앱 JSON 로그 → Filebeat → Elasticsearch → Kibana
탐지: `scripts/detector.py` (규칙: `docs/detection-rules.md`) → 차단 목록 → 웹 앱 403
인프라: Zabbix(+agent2) → Grafana

## 실행
1. Docker Desktop 설치 후 `.env.example`을 `.env`로 복사하고 값을 채운다.
2. `docker compose up -d --build`
3. 사이트: http://localhost:8080  /  Kibana: http://localhost:5601
4. 인프라 관제(선택): `docker compose --profile monitoring up -d` → Zabbix http://localhost:8081, Grafana http://localhost:3000
5. Kibana 데이터 뷰 생성: `docker compose exec kibana sh /monitoring/kibana-setup.sh`

## 테스트 트래픽 / 탐지 검증
`docker compose run --rm traffic --scenario <normal|injection|bruteforce|bot|spam|keyword_flood|mixed> --count N`
`docker compose run --rm --no-deps detector python /scripts/evaluate.py`

모든 포트는 127.0.0.1에만 열려 있으며, 테스트 트래픽은 로컬 환경으로만 보낸다.
