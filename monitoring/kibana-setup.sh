#!/bin/sh
# Kibana Data View(로그를 조회하는 기준) 생성. 인덱스가 생긴 뒤에 실행한다.
KB=http://localhost:5601

echo "Kibana 준비를 기다리는 중..."
i=0
until curl -s "$KB/api/status" | grep -q '"level":"available"'; do
  i=$((i+1))
  if [ "$i" -gt 60 ]; then echo "Kibana가 준비되지 않았습니다."; exit 1; fi
  sleep 5
done

create() {
  curl -s -X POST "$KB/api/data_views/data_view" \
    -H "kbn-xsrf: true" -H "Content-Type: application/json" \
    -d "{\"override\":true,\"data_view\":{\"id\":\"$1\",\"title\":\"$2\",\"name\":\"$3\",\"timeFieldName\":\"@timestamp\"}}" \
    > /dev/null && echo "생성 완료: $3"
}

create any-sports-nginx 'any-sports-nginx-*' 'Nginx 접속 로그'
create any-sports-app 'any-sports-app-*' '앱 이벤트 로그'
create any-sports-detector 'any-sports-detector-*' '탐지 이벤트 로그'
