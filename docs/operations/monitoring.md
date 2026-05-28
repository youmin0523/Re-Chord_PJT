# 운영 모니터링 (Observability)

운영 환경의 살아있음·정상 동작·사용자 영향 사고를 *조용히 놓치지 않게*
하는 게이트. 모든 신호는 코드에 이미 연결되어 있고 (`backend/app/core/
observability.py`, ProgressPanel WS reconnect 상태, accuracy gate JSON),
이 문서는 외부 도구 (Sentry / Grafana / 알람 채널)와 어떻게 묶을지를
정합니다.

---

## 0. 운영 지표 한눈에

| 영역 | 지표 | 임계값 | 신호 위치 |
|------|------|--------|-----------|
| 가용성 | `/health` 응답 시간 | p95 < 1s | uptime monitor |
| 가용성 | `/health` 200 rate | ≥ 99% / 5min | uptime monitor |
| 사용자 영향 | Job 실패율 (status="error") | < 5% / hour | 자체 로그 / Sentry |
| AI 품질 | accuracy gate 통과 여부 | PASS | nightly CI |
| AI 품질 | `backend_summary.fallbacks` non-empty 비율 | < 2% jobs | 자체 로그 |
| 사용자 경험 | 분리 grade D/E 비율 | < 1% jobs | `job.meta.quality_grade` |
| 사용자 경험 | WS 재연결 실패 (`failed` 이벤트) | < 0.5% 세션 | 클라이언트 텔레메트리 |
| 비용 | OpenAI 일 사용량 | < $20/day (조정 가능) | OpenAI 대시보드 |
| 보안 | 인증 실패 401 비율 | < 1% / min | Cloud Run 로그 |
| 인프라 | GPU 메모리 사용률 | < 90% | Cloud Run metrics |

---

## 1. Sentry — 에러 / 트레이스

### 1.1 활성화

코드는 이미 `backend/app/core/observability.py:setup_logging()` 에서
`SENTRY_DSN` env 가 비어있지 않으면 자동 초기화. 활성화하려면:

```bash
# .env (로컬) 또는 Cloud Run Secret Manager
SENTRY_DSN=https://<key>@<project>.ingest.sentry.io/<id>
RECHORD_ENV=prod
RECHORD_RELEASE=0.3.0
SENTRY_TRACES_SAMPLE_RATE=0.05    # 5% 트레이스. 트래픽 늘면 0.01로
```

### 1.2 보낼 / 보내지 말 정보

자동 캡처:
- 모든 미처리 예외 (FastApiIntegration)
- ERROR 레벨 로그 (LoggingIntegration, level=INFO event_level=ERROR)
- HTTP 컨텍스트 (URL · status · UA)

수동 캡처 위치 (`capture_exception(exc, job_id=, stage=)`):
- 오케스트레이터 각 단계 실패 시 tag로 stage 추가
- 챗봇 LLM 호출 실패 시 (구현 예정)

**보내지 말 정보** (Sentry 콘솔에서 PII Scrub):
- 사용자가 업로드한 음원 파일 경로의 원본 파일명 (잠재적 PII)
- 채팅 메시지 본문 (별도 정책 필요 — 사용자 동의 받고만)
- `.env` 의 키 값

### 1.3 알람 룰 (Sentry → Slack/이메일)

| 룰 | 조건 | 채널 |
|----|------|------|
| New issue | 신규 에러 첫 발생 | #alerts (대기 인지) |
| Issue spike | 동일 에러 분당 10건 초과 | #pager (즉시 대응) |
| Release regression | 새 RECHORD_RELEASE 배포 후 신규 에러 | #pager |
| Authentication failures | 401 분당 50건 초과 | #security |

Sentry 콘솔 → Settings → Alerts → "Create Alert Rule" 에서 위 조건
입력. Slack/이메일 integration은 사전 등록.

---

## 2. Grafana / Loki — 로그 + 메트릭

### 2.1 로그 포맷

`RECHORD_LOG_FORMAT=json` 강제 (`docs/operations/secrets_management.md`
참조). 구조:

```json
{
  "ts": "2026-05-28T10:23:00Z",
  "lvl": "INFO",
  "logger": "backend.app.workers.orchestrator",
  "msg": "Ingested mp3 48000Hz 180.0s",
  "job_id": "abc123",
  "stage": "ingest",
  "source": "https://..."
}
```

`structlog.contextvars`로 job_id/stage가 자동 바인딩. Loki 라벨로
`job_id`, `stage`, `RECHORD_ENV` 가 필터링 가능합니다.

### 2.2 Grafana 대시보드 (3 패널 기본)

1. **Job throughput** — `count(rate(log{stage="encode"})) by (5m)`
2. **Stage latency p95** — 각 stage 별 elapsed 통계
3. **Fallback rate** — `count(log{level="WARNING"}) / count(log{level="INFO"})`

대시보드 JSON 템플릿은 별도 git issue로 추적 (이번 패스 외).

### 2.3 알람 룰

| 룰 | 쿼리 (예시) | 임계 |
|----|-------------|------|
| Job 실패율 급증 | `rate(log{level="ERROR",stage=~".*"}[5m])` | > 0.05 |
| 분리 SDR 베이스라인 하락 | accuracy_thresholds.json 가공 | min 미달 |
| LUFS 목표 미달 | `log{key="lufs_error_db"} > 1.5` | 발생 시 |
| WebSocket reconnect 폭증 | 클라이언트 텔레메트리 | > 5% 세션 |

---

## 3. 클라이언트 텔레메트리 (선택)

### 3.1 WS 재연결 메트릭

`openProgressSocket` 의 onStatus 콜백에서 `reconnecting` / `failed` 이벤트를
서버로 send하면 백엔드에서 집계 가능. 현재 미구현 (수집 시 동의 필요).

권장 구조:

```js
// frontend/src/lib/telemetry.js (예정)
window.addEventListener("rechord:ws-status", (ev) => {
  if (ev.detail.state === "failed" || ev.detail.state === "reconnecting") {
    navigator.sendBeacon("/api/telemetry/ws", JSON.stringify({
      state: ev.detail.state,
      attempt: ev.detail.attempt,
      ts: Date.now(),
    }));
  }
});
```

### 3.2 코어 웹 바이탈 (Phase B)

- LCP / CLS / INP — Vercel Analytics 또는 web-vitals 라이브러리
- 모바일 vs 데스크탑 분리
- 페이지별 (Landing / Home / Job / Performance)

---

## 4. 외부 API 가용성 (OpenAI / Anthropic / Cloud Run)

### 4.1 OpenAI

- 콘솔에서 월 한도 알람 ($50 → #alerts, $100 → #pager)
- 429 / 503 응답율 추적 → `backend/app/chat/ratelimit.py` 가 사용자별
  토큰버킷 적용 중. 외부 429는 별도 fallback (Anthropic) 도입 검토.

### 4.2 클라우드

- Cloud Run 인스턴스 시작 시간 → 콜드 스타트 알람 (60s 초과)
- Cloudflare R2 4xx/5xx → API 토큰 권한 점검
- Supabase RLS 위반 알람 (보안)

---

## 5. 사고 대응 (Incident response)

### 5.1 Severity 등급

| 등급 | 정의 | 대응 시간 |
|------|------|-----------|
| **SEV-1** | 전체 서비스 다운 | 15분 내 알림 + 1시간 내 복구 시도 |
| **SEV-2** | 일부 사용자 영향 (변환 실패율 ≥ 10%) | 1시간 내 알림 + 8시간 내 |
| **SEV-3** | 개별 사용자 영향 / 비기능적 (UI 깨짐) | 다음 영업일 |
| **SEV-4** | 사용자 불편 적음 (모니터링 잡음) | 주간 리뷰 |

### 5.2 SEV-1 체크리스트

1. `/health` 상태 확인 — 200 응답하는지
2. Cloud Run 콘솔 → 최근 deploy / instance health
3. Sentry 에러 burst 확인
4. Postgres·Redis 연결 상태 (`SELECT 1`, `redis-cli ping`)
5. OpenAI / 외부 API 상태 페이지
6. 영향 범위 추정 → 사용자 공지 (앱 내 배너 + Twitter/X)
7. 롤백 가능하면 직전 commit으로 (Cloud Run revision rollback)

### 5.3 사고 후 (Post-mortem)

- 5 whys 분석
- 재발 방지 액션 → GitHub Issue 트래킹
- 알람 룰 조정 (놓친 신호가 있으면 임계값/룰 수정)

---

## 6. 헬스 체크 엔드포인트 활용

`/health` 응답 구조:

```json
{
  "status": "ok",
  "version": "0.3.0",
  "tools": [
    {"name": "ffmpeg", "version": "8.1", "available": true},
    ...
  ]
}
```

uptime monitor (UptimeRobot / BetterStack 등)에서:
- 1분마다 `/health` GET
- `tools[*].available == true` 까지 검증하려면 응답 JSON 파싱
- 알람 → 1분 이상 down 시 #pager

`/ops/install_hints` 도 운영자 진단용:
- `all_installed: false` 시 어떤 SOTA 의존성이 빠졌는지

---

## 7. 운영자 메모

이 문서는 *코드에 이미 연결된* 신호의 외부 도구 매핑 가이드입니다.
새 알람 룰을 추가할 때는:

1. 측정값이 코드에서 실제로 emit 되는지 grep (없으면 추가 PR)
2. 임계값은 [[verification-status]] 의 베이스라인 + 여유 (e.g.
   accuracy_thresholds.json의 min 값 ± 5%)
3. Slack/이메일 채널 분리 — `#alerts` (인지용) vs `#pager` (즉시 대응)
4. 거짓 양성률 검토 (월 1회) — 너무 자주 울면 무시당함
