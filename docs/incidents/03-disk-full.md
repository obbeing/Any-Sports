# 장애 보고서 03: 디스크 사용률 급증 (용량 부족 경보)

| 항목 | 내용 |
|---|---|
| 장애 유형 | 디스크 용량 부족 (테스트 장애, 컨테이너 내부 200MB 임시 디스크) |
| 발생 시각 (KST) | 2026-11-24 약 00:21 (1차 채우기, 사용률 85%) |
| 탐지 시각 / 탐지 방법 | 00:25:37 / Zabbix 파일시스템 트리거 `Space is low (used > 80%)` (Warning) |
| 심각 단계 | 00:26경 95%로 증가 → 00:30:37 `Space is critically low (used > 90%)` (Average) |
| 탐지 지연 | Warning 약 4분, Critical 약 4분 37초 (트리거가 5분 지속 조건을 적용) |
| 복구 시각 | 00:32경 (파일 삭제, 사용률 0%) |
| 경보 해소 | 00:32:37 (Warning, Critical 동시 RESOLVED) |
| 심각도 | 중간 (실제 서비스와 분리된 테스트 디스크) |

## 1. 재현 방법
실제 PC 디스크를 채우지 않기 위해 `zabbix-agent` 컨테이너에 200MB tmpfs(`/mnt/labdisk`)를 마운트했다. 이 디스크에만 파일을 써서 사용률을 올렸다.
```
docker compose exec zabbix-agent dd if=/dev/zero of=/mnt/labdisk/fill.bin bs=1M count=170
docker compose exec zabbix-agent dd if=/dev/zero of=/mnt/labdisk/fill2.bin bs=1M count=20
```
`df -h` 측정: 0% → 85%(170M) → 95%(190M, 여유 10M).

## 2. 탐지
- Zabbix의 `Linux by Zabbix agent` 템플릿 파일시스템 발견(LLD)으로 `/mnt/labdisk`가 자동 등록됐다. 발견 대상은 호스트 매크로 `{$VFS.FS.FSNAME.MATCHES}`, `{$VFS.FS.FSTYPE.MATCHES}`에 `/mnt/labdisk`와 tmpfs를 추가해 허용했다.
- 시간대별 경보:

| 시각 (KST) | 사용률 | 경보 |
|---|---|---|
| 00:25:37 | 85% | Warning: `Space is low (used > 80%)` |
| 00:30:37 | 95% | Average: `Space is critically low (used > 90%)` |

- 기본 트리거는 기준 초과가 5분 가까이 이어져야 발생하므로, 일시적 급증으로 인한 오탐을 줄이는 대신 탐지가 4분가량 늦다.
- Critical이 발생하자 Warning 줄이 목록에서 사라졌다(템플릿의 트리거 의존 관계로 단계가 합쳐짐).

## 3. 영향
- 사용률 증가 중과 경보 중에도 이 디스크는 웹 서비스와 분리돼 있어 사이트 응답에는 영향이 없었다.
- 실제 운영 환경이었다면 로그와 DB 파일이 쓰는 디스크가 가득 차 쓰기 오류(로그 유실, DB 쓰기 실패)로 이어질 수 있다. 이 부분은 이번에 재현하지 않았고, 일반적인 위험으로만 기술한다.

## 4. 원인 분석
`df -h`로 `/mnt/labdisk` 사용률이 85%, 95%인 것을 확인했다. 원인은 `fill.bin`, `fill2.bin` 두 파일(총 190MB)이었다. 운영에서는 `du -sh`로 용량이 큰 디렉터리를 좁혀 가며 로그 폭증, 오래된 파일 등 원인을 찾는다.

## 5. 조치와 복구
```
docker compose exec zabbix-agent rm /mnt/labdisk/fill.bin /mnt/labdisk/fill2.bin
```
`df -h`에서 사용률 0% 확인 (00:32경).

## 6. 복구 확인
- Zabbix 경보 RESOLVED 시각 00:32:37 (Warning 지속 7분, Critical 지속 2분).
- 파일 삭제 후 약 1분 이내에 해소됐다.

## 7. 개선점
- Warning(80%) 단계에서 담당자에게 알림이 가도록 Slack 등 알림 연결이 필요하다. 지금은 화면을 봐야만 알 수 있다.
- 로그 로테이션과 보존 기간 설정(Docker 로그 `max-size`, Elasticsearch 인덱스 수명 관리)으로 용량 증가를 예방한다.
- 사용률뿐 아니라 증가 속도(예: 1시간 후 가득 참 예측)를 보는 트리거를 추가하면 더 일찍 대응할 수 있다.
- 한계: 이번 실험은 200MB 임시 디스크로 재현한 것이며, 호스트(WSL2 VM) 디스크의 실제 용량 부족은 시험하지 않았다.

## 증적
- [x] `df -h` 85% / 95% / 0% 출력
- [x] Zabbix 경보 발생 Warning (00:25:37)
- [x] Zabbix 경보 발생 Critical (00:30:37)
- [x] Zabbix 경보 해결(RESOLVED, 00:32:37)
- [ ] 장애 중 사이트(`http://localhost`) 응답 확인
