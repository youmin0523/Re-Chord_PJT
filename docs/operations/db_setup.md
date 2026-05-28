# DB 셋업 가이드 — "호스트만 받으면 즉시 붙는" 절차

베타 단계는 in-memory 잡 레지스트리(`backend/app/core/jobs.py::registry`)로
DB 없이 동작합니다. 호스트형 Postgres를 받는 순간 — Supabase / Neon / RDS
— 다음 3-step만 거치면 즉시 연결됩니다.

---

## 사전 준비

- `pyproject.toml` 의 `[saas]` 추가 의존성을 설치:
  ```bash
  uv pip install -e ".[saas]"
  ```
- Postgres가 살아있는지 확인 (로컬·관리형 둘 다):
  - 로컬: `Get-Service postgresql*` (Windows) / `pg_isready` (Linux)
  - 관리형: 콘솔에서 connection string 받기

---

## Step 1. DB / 유저 생성 + 마이그레이션

### 로컬 (PostgreSQL 16 native, Windows)

```powershell
# 한 줄로 끝 — psql 자동 탐색, alembic까지 자동
.\scripts\setup_postgres.ps1
```

기본값은 `rechord` 유저, `rechord` DB, password `rechord_dev`. 변경하려면:

```powershell
.\scripts\setup_postgres.ps1 -DbPassword 'pw' -DbUser 'app'
```

### 로컬 (Linux / macOS / WSL)

```bash
./scripts/setup_postgres.sh           # 기본값
DBPASSWORD='pw' DBUSER='app' ./scripts/setup_postgres.sh
```

### 관리형 (Supabase 예시)

Supabase 콘솔 → Project Settings → Database → Connection string에서 `URI`
복사. 비밀번호 부분(`[YOUR-PASSWORD]`)을 본인 DB 비밀번호로 교체.

```powershell
.\scripts\setup_postgres.ps1 `
    -PgHost db.abcdefghij.supabase.co `
    -AdminUser postgres `
    -AdminPassword 'SUPABASE_DB_PASSWORD' `
    -DbName postgres `
    -DbUser postgres `
    -DbPassword 'SUPABASE_DB_PASSWORD'
```

(Supabase는 별도 유저 생성 대신 `postgres` 슈퍼유저로 그대로 사용해도
무방합니다. 보안 등급을 더 올리려면 RLS-제한 유저를 별도 생성.)

```bash
PGHOST=db.abcdefghij.supabase.co \
PGADMINUSER=postgres \
PGADMINPASSWORD='SUPABASE_DB_PASSWORD' \
DBNAME=postgres \
DBUSER=postgres \
DBPASSWORD='SUPABASE_DB_PASSWORD' \
  ./scripts/setup_postgres.sh
```

### Neon / RDS

요청 시 connection string에 `?sslmode=require` 가 붙어야 합니다.
`DATABASE_URL` 환경변수에 그대로 넣으면 asyncpg가 자동 인식합니다.

---

## Step 2. `.env` / Secret Manager에 DATABASE_URL 등록

setup 스크립트가 종료될 때 출력하는 `DATABASE_URL=...` 라인을 `.env`에
추가하거나 (로컬), Cloud Run 환경변수 / Secret Manager에 등록합니다.
형식:

```
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME[?sslmode=require]
```

`backend/app/config.py` 의 `Settings` 클래스가 이 값을 자동 로드합니다.

---

## Step 3. 백엔드 재기동 + 헬스 체크

```bash
# 로컬
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 7860

# 컨테이너
docker compose up -d backend
```

확인:

```bash
curl http://127.0.0.1:7860/health
```

응답에 `status: "ok"`가 보이면 OK. 잡을 한 번 만들어 (예: `/jobs` POST)
DB에 row가 들어오는지 확인:

```bash
psql -h <HOST> -U <USER> -d <DBNAME> -c "SELECT id, status, stage FROM jobs LIMIT 5;"
```

---

## 회수 / 변경

- **DB 비밀번호 회전**: `setup_postgres.ps1`을 다시 실행하면 `CREATE ROLE`은
  skip되고 권한 grant만 재적용됩니다. 비밀번호만 바꾸려면 별도 SQL:
  `ALTER ROLE rechord WITH PASSWORD 'newpw';`
- **스키마 업그레이드**: 마이그레이션 파일 추가 후 `uv run alembic -c
  backend/app/db/alembic.ini upgrade head` 한 번 더 실행.
- **롤백**: `uv run alembic -c backend/app/db/alembic.ini downgrade -1` 또는
  특정 revision으로.
- **완전 초기화 (위험)**: `DROP DATABASE rechord;` 후 setup 재실행.
  사용자 데이터 즉시 소실.

---

## 트러블슈팅

| 증상 | 진단 / 해결 |
|------|-------------|
| `psql: error: connection refused` | Postgres 데몬 안 살아있음 — 서비스 확인 |
| `FATAL: password authentication failed` | admin password 오타 / pg_hba.conf의 인증 방식 |
| `alembic.util.exc.CommandError: Can't locate revision` | `backend/app/db/migrations/versions/` 가 비어있거나 손상 — git diff 확인 |
| `sqlalchemy.exc.OperationalError: SSL required` | URL에 `?sslmode=require` 추가 (Neon/Supabase) |
| `relation "jobs" does not exist` | Step 1 alembic 단계가 실패 — 로그 확인 |
| `permission denied for schema public` | Postgres 15+ 에서 `GRANT ALL ON SCHEMA public TO rechord;` 추가 필요 |

---

## Phase A로 되돌리기

`DATABASE_URL` 환경변수를 unset하고 백엔드 재기동하면 즉시 in-memory
registry로 폴백합니다. 데이터 손실 없음 (재기동 시 RAM 비워질 뿐).
