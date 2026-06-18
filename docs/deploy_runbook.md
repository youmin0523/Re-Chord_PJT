# Re:Chord — 내일 오전 배포 런북 (Step-by-Step)

> 작성: 2026-06-18 · 대상: 베타 출시 (로그인·결제 보류, **게스트 모드**)
>
> 이 문서는 "어제 멈춘 지점"부터 끝까지 복붙으로 따라가도록 만든 실전 체크리스트다.
> 일반 설명은 `docs/deployment.md`(Phase B/관측/정확도 게이트) 참고.

## 현재 상태 (실측 2026-06-18)

| 항목 | 상태 |
|---|---|
| pytest | ✅ **223 passed, 3 skipped, 0 failed** |
| frontend `npm run build` | ✅ 성공 (~1s, 번들 OK) |
| frontend vitest | ✅ 27 passed |
| Supabase 프로젝트 | ✅ 생성됨 (`nvkhlstspqotlkiybtel`, Seoul) + Alembic 적용됨 |
| `youmin.site` (Cloudflare 등록) | ✅ resolve 됨 |
| `cloudflared` | ✅ 설치됨 (winget) — **단, named tunnel 미생성** (`~/.cloudflared` 없음) |
| `api.youmin.site` | ❌ **아직 없음** (NXDOMAIN) ← 어제 멈춘 지점 |
| Vercel 프론트 배포 | ❌ 아직 안 함 |

**남은 일 = ① 백엔드 prod 설정 → ② Cloudflare named tunnel(api.youmin.site) → ③ Vercel 프론트 배포(youmin.site) → ④ 스모크 테스트.**

## 배포 아키텍처 (베타)

```
 사용자 브라우저
   │  https://youmin.site            (정적 SPA)
   ▼
 Vercel (frontend/dist)
   │  fetch/ws → https://api.youmin.site   (크로스 오리진 → CORS 필요)
   ▼
 Cloudflare named tunnel  ── 암호화 터널 ──▶  로컬 RTX 5070 PC
                                              uvicorn 127.0.0.1:7860 (FastAPI)
                                              + GPU 분리/분석 파이프라인
 Supabase: DB(선택) / Auth(보류)   OpenAI: 챗봇
```

가정(다르면 아래 도메인만 치환):
- 앱 도메인 = `youmin.site` (+ `www.youmin.site`)
- 백엔드 도메인 = `api.youmin.site`
- 백엔드는 **로컬 RTX 5070 PC에서 상시 실행** (이 PC가 켜져 있어야 서비스됨)
- 로그인/결제 **보류** → 게스트 모드로 출시 (`VITE_SUPABASE_*` 미설정해도 정상 동작)

---

# 0. (전날 밤 권장) 코드 push & 사전 점검

```bash
cd "c:/Users/Codelab/Desktop/PROJECT/Portfolio/MR Project"

# 0-1. 이번에 고친 것들 커밋 (큐 재시작 버그·CORS 설정화·artifact prune·vercel.json)
git add backend/app/core/queue.py backend/app/config.py backend/app/main.py \
        backend/app/workers/orchestrator.py .env.example \
        frontend/vercel.json docs/deploy_runbook.md
git commit -m "feat(deploy): CORS env-config + queue restart fix + SPA vercel.json + runbook"
git push

# 0-2. 로컬 그린 재확인 (배포 전 마지막 게이트)
uv run pytest -q          # 223 passed 기대
cd frontend && npm run build && npm run test && cd ..

# 0-3. 임시 산출물 정리 (커밋 금지 파일)
#   _job_ids.txt, 추출결과_MR/ 은 로컬 테스트 잔여물 → .gitignore 확인/삭제
```

> ⚠️ 정리: `_job_ids.txt`, `추출결과_MR/` 는 git 추적 대상이 아니어야 한다. 이미 `.gitignore`에 `data/`가 있으니 산출물은 `data/output`으로 쓰되, 루트의 두 항목은 삭제하거나 `.gitignore`에 추가.

---

# 1. 백엔드 prod 설정 (로컬 RTX 5070 PC)

## 1-1. `.env` 에 prod 값 추가/수정

`.env` 파일에서 아래를 설정한다 (없는 줄은 추가):

```ini
# 배포 프론트 오리진 허용 (이게 없으면 브라우저가 모든 API 응답을 CORS로 차단함)
CORS_ALLOW_ORIGINS=https://youmin.site,https://www.youmin.site

# 공개 노출되므로 운영 엔드포인트 잠금 (랜덤 토큰 생성해서 넣기)
RECHORD_OPS_TOKEN=<아래 명령으로 생성한 랜덤 문자열>

# 관측(선택이지만 권장)
RECHORD_ENV=prod
RECHORD_RELEASE=0.3.0
RECHORD_LOG_FORMAT=json
```

랜덤 ops 토큰 생성:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> `CORS_ALLOW_ORIGINS` 는 정확히 `스킴+호스트`만 (뒤 슬래시·경로 금지). Vercel 프리뷰 URL로도 테스트하려면 그 `https://<...>.vercel.app` 도 콤마로 추가.
>
> `RECHORD_OPS_TOKEN` 을 설정하면 `/ops/cleanup`·`/ops/prewarm`·`/ops/disk` 가 `X-Ops-Token` 헤더 없이는 401이 된다. 설정 안 하면 **공개로 누구나 호출 가능** → 반드시 설정.

## 1-2. 백엔드 기동

```powershell
# RTX 5070 PC에서 (PowerShell)
cd "c:\Users\Codelab\Desktop\PROJECT\Portfolio\MR Project"
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 7860
```

확인:
```bash
curl http://127.0.0.1:7860/health           # {"status":"ok",...}
curl http://127.0.0.1:7860/ops/install_hints # SOTA 모델 설치 현황(정확도 영향) 확인
```

`/ops/install_hints` 의 `all_installed:false` 면 누락 모델만큼 정확도가 떨어진다(크래시는 아님 — graceful fallback). 베타 출시엔 그대로 가도 되고, 품질을 올리려면 `docs/deployment.md §1` 의 설치 명령 실행.

> 상시 실행 권장: PowerShell 창을 닫아도 살아있게 하려면 `Start-Process` 로 백그라운드 창에 띄우거나, NSSM/작업 스케줄러로 서비스화. 베타엔 전용 창 1개로도 충분.

---

# 2. Cloudflare named tunnel (api.youmin.site) — 어제 멈춘 지점

quick tunnel(`*.trycloudflare.com`)은 재시작마다 URL이 바뀌므로 **named tunnel**로 고정한다.

```powershell
# 2-1. Cloudflare 로그인 (브라우저 열림 → youmin.site 영역 선택 → cert.pem 저장)
cloudflared tunnel login

# 2-2. 터널 생성 (자격증명 json 이 ~/.cloudflared/<UUID>.json 으로 생성됨)
cloudflared tunnel create rechord

# 2-3. UUID 확인
cloudflared tunnel list
```

## 2-4. 설정 파일 작성

`C:\Users\Codelab\.cloudflared\config.yml` 생성:

```yaml
tunnel: <위에서 받은 UUID>
credentials-file: C:\Users\Codelab\.cloudflared\<UUID>.json

ingress:
  - hostname: api.youmin.site
    service: http://127.0.0.1:7860
  - service: http_status:404
```

> WebSocket(`/jobs/{id}/progress`)은 cloudflared가 자동 처리한다. 별도 설정 불필요.

## 2-5. DNS 라우트 + 실행

```powershell
# api.youmin.site → 터널 CNAME 자동 생성
cloudflared tunnel route dns rechord api.youmin.site

# 우선 포그라운드로 테스트
cloudflared tunnel run rechord
```

다른 창에서:
```bash
curl https://api.youmin.site/health     # {"status":"ok"} 나오면 성공
```

## 2-6. 윈도우 서비스로 상시 실행

```powershell
# config.yml 을 읽어 서비스 설치 (부팅 시 자동 시작)
cloudflared service install
# 시작/상태
Start-Service cloudflared
Get-Service cloudflared
```

> 서비스가 기본 config 경로(`C:\Users\Codelab\.cloudflared\config.yml`)를 못 찾으면 `cloudflared --config <경로> service install` 로 지정.

---

# 3. 프론트엔드 배포 (Vercel → youmin.site)

`frontend/vercel.json` 은 이미 생성됨 (SPA rewrite + 보안 헤더). 딥링크(`/job/:id`) 새로고침 404 방지 포함.

## 3-1. Vercel 프로젝트 import (대시보드)

1. <https://vercel.com> 로그인 → **Add New → Project** → GitHub `youmin0523/Re-Chord_PJT` import.
2. **Root Directory** = `frontend` (★중요 — 모노레포라서 반드시 지정).
3. Framework = **Vite** (자동 감지), Build = `npm run build`, Output = `dist` (vercel.json이 명시).

## 3-2. 환경변수 (Production scope)

| Key | Value |
|---|---|
| `VITE_API_BASE` | `https://api.youmin.site` |

로그인 보류 → **게스트 모드**면 위 1개만으로 충분. (Supabase 변수 미설정 시 로그인 UI는 자동 비활성, 앱은 정상 동작.)

나중에 로그인을 켤 때만 추가 (지금은 생략 권장):
```
VITE_AUTH_PROVIDER=supabase
VITE_SUPABASE_URL=https://nvkhlstspqotlkiybtel.supabase.co
VITE_SUPABASE_ANON_KEY=<anon/publishable 키 — service_role 절대 금지>
```

> 🚫 **service_role 키는 절대 Vercel(프론트)에 넣지 말 것.** anon(publishable) 키만 브라우저 노출 안전.

## 3-3. 배포 & 도메인 연결

1. **Deploy** → `https://<프로젝트>.vercel.app` 생성됨. 먼저 이 URL로 동작 확인.
   - 이때 임시로 백엔드 `CORS_ALLOW_ORIGINS` 에 그 `*.vercel.app` 도 추가하면 테스트 편함.
2. Vercel → Project → **Settings → Domains** → `youmin.site` 와 `www.youmin.site` 추가.
3. Vercel이 요구하는 DNS 레코드를 **Cloudflare DNS**에 추가:
   - apex `youmin.site` → **A** `76.76.21.21`
   - `www` → **CNAME** `cname.vercel-dns.com`
   - (이미 `api` CNAME은 2-5에서 생성됨 — 건드리지 말 것)
   - Cloudflare SSL/TLS 모드 = **Full** 권장. apex 레코드는 Vercel 검증 동안 **DNS only(회색 구름)** 로 두는 게 안전.

> DNS는 Cloudflare에 그대로 두고 레코드만 추가한다(네임서버를 Vercel로 옮기지 않음 — 터널이 Cloudflare DNS에 의존하므로).

---

# 4. (지금은 생략) 로그인/Supabase Auth — 출시 후 별도 작업

로그인은 보류이므로 내일은 **건너뛴다.** 나중에 켤 때 순서만 기록:

1. Kakao Developers → 비즈앱 → REST 키 → Supabase Auth → Kakao provider 활성.
2. Supabase → Auth → URL Configuration → **Redirect URLs** 에 `https://youmin.site/auth/callback` 추가, Site URL = `https://youmin.site`.
3. Vercel에 `VITE_SUPABASE_*` 3개 추가 후 재배포.
4. DB가 필요한 기능(consents 등)을 쓸 때만 백엔드 `.env` 의 `DATABASE_URL` 활성 + `uv run alembic -c backend/app/db/alembic.ini upgrade head`.

게스트 모드에선 잡 처리에 DB가 필요 없다(인메모리 레지스트리).

---

# 5. 🔐 시크릿 회전 (출시 전 강력 권장)

`.env` 의 라이브 키들이 작업 중 노출됐을 가능성이 있으면 출시 전에 회전한다. 최소한 **service_role 키**는 권한이 가장 세므로 우선:

- **Supabase service_role / DB 비밀번호**: Supabase Dashboard → Settings → API(키 재발급) / Database(비밀번호 reset). 새 값으로 `.env` `SUPABASE_SERVICE_ROLE_KEY`·`DATABASE_URL` 갱신. (DB URL의 `@`,`,` 같은 특수문자는 `%40`,`%2C` 로 URL-encode — 이미 적용돼 있음.)
- **OpenAI 키**: platform.openai.com → API keys → 재발급 → `.env` `OPENAI_API_KEY`.
- **Tavily 키**: tavily 대시보드 → 재발급 → `.env` `TAVILY_API_KEY`.

회전 후 백엔드 재시작. 프론트(Vercel)에는 시크릿이 없어야 정상(anon 키만).

---

# 6. 스모크 테스트 (배포 직후 필수)

```bash
# 6-1. 백엔드 (터널 경유)
curl https://api.youmin.site/health
curl -X POST https://api.youmin.site/ops/cleanup     # 401 나와야 정상 (ops 토큰 잠금 확인)
```

브라우저에서 `https://youmin.site`:
- [ ] 랜딩/앱 로딩 OK, 콘솔에 **CORS 에러 없음** (DevTools → Network)
- [ ] 짧은 오디오 업로드 → 잡 생성 → 진행률(WebSocket) 갱신 → 완료
- [ ] 결과 다운로드(반주/보컬) 동작
- [ ] 딥링크 새로고침: `https://youmin.site/job/<id>` 직접 열기 → 404 아님 (vercel rewrite 확인)
- [ ] 챗봇 응답 (OPENAI 키 설정 시), 한국어/영어
- [ ] 모바일 뷰포트에서 레이아웃 OK

문제 시 빠른 진단:
- CORS 에러 → 백엔드 `.env` `CORS_ALLOW_ORIGINS` 에 실제 프론트 오리진 정확히 들어갔는지 + 백엔드 재시작했는지.
- API 503/타임아웃 → 백엔드 uvicorn 떠 있는지, cloudflared 서비스 동작 중인지(`Get-Service cloudflared`).
- 새로고침 404 → Vercel에 `vercel.json` rewrite 반영됐는지(재배포).

---

# 7. 롤백 / 중단

- 프론트: Vercel → Deployments → 이전 배포 **Promote to Production** (즉시 롤백).
- 백엔드: uvicorn 창 종료 → 터널은 살아있어도 502. 완전 중단은 `Stop-Service cloudflared`.
- 도메인 내리기: Cloudflare에서 `api`/apex 레코드 일시 비활성.

---

## 부록: 이번 배포 준비에서 함께 고친 것

| 변경 | 파일 | 이유 |
|---|---|---|
| CORS 오리진 env 설정화 | `backend/app/config.py`, `main.py` | localhost만 허용 → 배포 프론트가 모든 API 차단되던 **실제 블로커** 해결 |
| 큐 재시작 버그 수정 | `backend/app/core/queue.py` | `_global_queue` 가 죽은 이벤트 루프에 바인딩돼 재부팅 시 모든 잡이 큐에 멈추던 문제(테스트 1건 실패의 근본 원인) |
| dangling artifact prune | `backend/app/workers/orchestrator.py` | cleanup이 지운 스크래치를 가리키는 artifact 키 제거 → `/download` 404·죽은 다운로드 버튼 방지 |
| SPA rewrite + 보안 헤더 | `frontend/vercel.json` | 딥링크 새로고침 404 방지 + nosniff/XFO/Referrer/Permissions 헤더 |

알려진 후속(비차단): 코드 detect 단계가 `sections_json` 을 쓰기 전에 읽어 다운비트 정렬 미세 품질 저하 — 크래시 아님, 추후 파이프라인 순서 조정.
