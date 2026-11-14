# Zabbix / Grafana 구성 메모
- 감시 대상: Docker Desktop(WSL2)의 리눅스 VM. 에이전트가 pid host로 VM의 CPU/메모리/디스크/프로세스를 수집한다.
- Zabbix: server + web + PostgreSQL + agent2 (7.0 LTS). Grafana: Zabbix 플러그인으로 지표 시각화.
- 접속: Zabbix http://localhost:8081, Grafana http://localhost:3000 (둘 다 127.0.0.1에만 열림)
- 기본 계정(Admin/zabbix)은 첫 로그인 직후 변경한다.
