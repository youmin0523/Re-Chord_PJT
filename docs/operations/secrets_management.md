# Secrets Management

운영 환경에서 사용하는 모든 비밀 (API 키·DB 접속 정보·OAuth 시크릿)의
저장·전달·회전·사고 대응 기준. 베타 단계는 단일 머신 / 단일 `.env`로
충분하지만, Phase B 진입 시 본 문서의 기준을 강제 적용합니다.

---

## 0. 절대 원칙

1. **`.env`는 git에 절대 커밋하지 않습니다.** `.gitignore`는 `*.env` +
   `!.env.example` 패턴으로 잠겨 있습니다. 새 환경변수를 추가할 때는
   `.env.example`에 키 이름만 (값 없이) 기록해 다른 개발자에게 알립니다.
2. **운영용 키와 개발용 키는 분리합니다.** OpenAI 등 키는 환경별 prefix
   (`OPENAI_API_KEY_DEV` / `_STAGE` / `_PROD`)로 발급하고, 사용 사이트에서
   `RECHORD_ENV`에 맞게 자동 선택합니다.
3. **사고 의심 시 키 회전이 최우선.** Slack/이메일/Git 등에 키가 노출된
   정황이 보이면 즉시 §4 절차로 회전.

---

## 1. 환경별 저장 위치

| 환경 | 저장소 | 접근 방법 |
|------|--------|-----------|
| 로컬 개발 | 프로젝트 루트의 `.env` (gitignored) | `python-dotenv` / `pydantic-settings`가 자동 로드 |
| Docker 컨테이너 (단일 인스턴스) | `docker compose` 환경변수 또는 `--env-file .env.production` | compose가 컨테이너에 주입 |
| Cloud Run (Phase B) | Google Cloud Secret Manager | 서비스 계정 IAM `roles/secretmanager.secretAccessor` |
| Cloudflare R2 / S3 (Phase B) | 환경변수 → AWS_ACCESS_KEY_ID 등으로 SDK 자동 인식 | 마운트하지 않고 IAM Role 권장 |
| CI/CD (GitHub Actions) | Repository Secrets / Environment Secrets | `${{ secrets.NAME }}` 만 사용, log 출력 금지 |

`docs/deployment.md` 의 ENV 베이스라인과 일관성을 유지합니다.

---

## 2. 필수 Secret 목록

다음 키들은 정식 출시 전 모두 설정 + 회전 정책을 갖춰야 합니다.

| 키 이름 | 용도 | 회전 주기 | 사고 시 영향 |
|---------|------|-----------|--------------|
| `OPENAI_API_KEY` | 챗봇 LLM | **90일** | 비용 폭주 / 채팅 컨텍스트 노출 |
| `ANTHROPIC_API_KEY` (옵션) | LLM 백업 | 90일 | 동일 |
| `SENTRY_DSN` | 오류 모니터링 | 180일 | 오류 메타데이터 노출 |
| `DATABASE_URL` | Postgres 접속 | 90일 (PG 사용자 비밀번호 회전) | DB 무단 접근 |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis 접속 | 90일 | 큐 무단 조작 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | R2 / S3 | **60일** | 사용자 오디오 노출·삭제 |
| `AUTH_PROVIDER` / `CLERK_JWKS_URL` (또는 Supabase) | 인증 검증 | 인증 제공자 기준 | 인증 우회 |
| `POSTGRES_PASSWORD` (compose 부트스트랩) | 초기 DB 생성용 | 1회용 | DB 무단 접근 |

§4의 회전 절차를 캘린더에 등록해 자동화합니다 (예: `gh actions schedule
rotate-keys.yml @monthly`).

---

## 3. .env.example 운영

- **새 환경변수를 코드에 도입할 때**:
  1. 코드 변경 시 `backend/app/config.py`의 `Settings`에 필드 추가
  2. `.env.example` 에 키 이름 + 한 줄 주석으로 용도 기재 (값은 비움)
  3. `docs/deployment.md` §0 의 표를 갱신
  4. 코드 리뷰 PR에 명시
- `.env.example` 자체는 git에 커밋합니다 (`.gitignore`의 `!.env.example`
  unignore).

예시:

```bash
# .env.example
# Re:Chord — 운영 환경변수 템플릿. 실제 값은 .env로 별도 작성.

RECHORD_ENV=dev                 # dev | stage | prod
RECHORD_LOG_FORMAT=text         # text | json
SENTRY_DSN=                     # https://...@sentry.io/123 (prod에서 필수)

OPENAI_API_KEY=                 # https://platform.openai.com/api-keys
DATABASE_URL=                   # postgresql+asyncpg://user:pass@host:5432/rechord
CELERY_BROKER_URL=              # redis://host:6379/1
```

---

## 4. 회전 절차 (Rotation)

### 4.1 정기 회전

1. 새 키를 발급 (각 제공자 콘솔)
2. Secret Manager / `.env.production` 에 신키를 *추가* (구키 유지)
3. Cloud Run / 컨테이너 재배포 → 신키 활성화
4. 24시간 동안 모니터링 (Sentry 에러 / Cloud Run 로그)
5. 정상 동작 확인 후 구키 폐기 (각 제공자 콘솔에서 revoke)
6. 회전 일자·담당자·신구 키 ID를 `docs/operations/rotation_log.md` 에
   기록

### 4.2 사고 대응 (Incident)

키 노출이 의심되는 즉시:

1. **24시간 골든 룰**: 1시간 내 구키 revoke + 신키 발급
2. 영향 범위 추정 (어디서·언제 노출됐는지)
3. OpenAI 노출 시 → 사용량 로그 확인 → 비용 abuse 여부 점검
4. Cloud Run 환경변수 즉시 신키로 교체 (rolling restart)
5. Postgres 키 노출 시 → 추가 사용자 생성·구사용자 password 폐기·
   PG `pg_stat_activity` 점검
6. 노출이 git 히스토리에 들어갔다면 `git filter-repo`로 히스토리 재작성 +
   force push (사용자 동의 후) + 모든 fork에 같은 작업 요청
7. KISA/PIPA 신고 의무 발생 여부 검토 (개인정보 침해 시 72시간 내 신고)

---

## 5. 부수 안전장치

- **사용량 알람**: OpenAI / GCP / Cloudflare 콘솔에서 월 한도 알람
  설정 (예: $50 도달 시 Slack #alerts)
- **IP 화이트리스트**: Postgres·Redis는 VPC 내부만, OpenAI API는 키만
  유효 (제공자가 IP 제한 미지원)
- **2FA**: 모든 제공자 콘솔 계정에 2FA 강제
- **로그 마스킹**: structlog 포맷터에 자동 마스킹 처리 (`****@****.com`,
  키 prefix 8자만)
- **백업**: Postgres 매일 스냅샷, R2 versioning 활성화

## 6. 로컬 개발자 온보딩 체크리스트

신규 협업자가 `.env`를 직접 받지 못하도록:

- [ ] `cp .env.example .env`
- [ ] 개발용 OpenAI 키 발급 (개인 계정, $5 한도)
- [ ] `SENTRY_DSN`은 비워두거나 dev DSN 사용
- [ ] `DATABASE_URL`은 로컬 `docker compose up postgres` 이후 자동
      매핑 (`postgresql+asyncpg://rechord:rechord_dev@localhost/rechord`)
- [ ] **운영 키를 절대 로컬 `.env`에 복사하지 않습니다.**
- [ ] `git status` 후 `.env`가 untracked 인지 확인

## 7. Phase B 진입 시 즉시 처리할 추가 작업

- Google Cloud Secret Manager 셋업 + Cloud Run 서비스 계정 IAM 부여
- Cloudflare R2 API 토큰 발급, IP 제한 가능 여부 점검
- Supabase service_role 키는 서버에서만, anon 키는 클라이언트에서만
- GitHub Actions Environments(`production`/`staging`) 분리 + 리뷰어 승인 후 배포
