# Load tests

[k6](https://k6.io) 기반 부하 테스트. 운영 출시 전 한 번, 이후 분기마다
재실행 권장.

## 설치

```bash
# Windows (chocolatey)
choco install k6

# macOS
brew install k6

# Linux (apt)
sudo gpg -k && \
    sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69 && \
    echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list && \
    sudo apt-get update && sudo apt-get install k6
```

## 시나리오

| 파일 | 목적 | 실행 |
|------|------|------|
| `k6_smoke.js` | 가벼운 읽기 경로 (health/formats/chat session) | `k6 run tests/load/k6_smoke.js` |
| (TODO) `k6_job_submit.js` | 실제 잡 제출 부하 (GPU 점유 ↑) | 출시 전 ad-hoc |
| (TODO) `k6_chat_stream.js` | SSE 스트림 동시 연결 | LLM 비용 주의 |

## 임계값 (smoke 기준)

- 95퍼센타일 응답 시간 < 600ms (health/formats 가벼운 경로)
- 실패율 < 1%
- 최대 20 동시 사용자

위 임계값은 베타 단계의 *최소 보장*. 정식 출시 시 다음 단계로 조정:

| 단계 | VU (vusers) | p95 latency | 실패율 |
|------|-------------|-------------|--------|
| 베타 | 20 | < 600ms | < 1% |
| Soft launch | 50 | < 800ms | < 1% |
| 정식 출시 | 100 | < 1000ms | < 0.5% |

## CI 통합 (선택)

GitHub Actions에서 매 PR마다 smoke 부하 (k6 cloud 또는 self-hosted runner):

```yaml
- name: k6 smoke
  uses: grafana/k6-action@v0.3.1
  with:
    filename: tests/load/k6_smoke.js
    flags: --vus 5 --duration 30s
```

비용/시간 고려 시 nightly cron으로 분리 권장.

## 주의

- 잡 제출 시나리오는 **GPU 메모리·디스크 공간을 빠르게 소진**합니다.
  순서: smoke → soak (1시간) → spike (5분) → stress (한계 찾기).
- 챗봇 스트림은 **OpenAI 비용**을 발생시킵니다. 부하 테스트 전 월 한도
  알람 켜고 실행하세요 ([secrets_management.md](../docs/operations/secrets_management.md) §5).
- 부하 중 Sentry / Cloud Run 메트릭을 동시에 관찰 → 어디서 깨지는지
  관찰 ([monitoring.md](../docs/operations/monitoring.md) §2).
