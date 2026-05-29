# Re:Chord

AR(보컬+반주) 음원을 MR(반주만)로 변환하고, 키·템포·코드·섹션·악보·가사·AUX 음색까지 한 번에 추출하는 플랫폼.
워십팀 / 솔로 연습 / 스튜디오 작업 모두를 위한 통합 도구.

---

## 환경

- **Python 3.11.15** (uv 관리)
- **Node.js 18+** (frontend dev/build)
- **ffmpeg 8.1 full** — librubberband, libsoxr, chromaprint 포함
- **rubberband-cli 3.3.0** — R3 finer 엔진 (`bin/rubberband-r3.exe`)
- **fluidsynth 2.5.4** — AUX reference DB 빌드용 (`bin/fluidsynth.exe`)
- **NVIDIA RTX 5070 Laptop GPU**, 8GB VRAM, CUDA 12.8, 드라이버 577.09+
- **PowerShell 5.1** (Windows 11) — Bash도 가능

---

## 빠른 시작

### 1) Python 환경 + 핵심 의존성

```powershell
# 가상환경 + 기본 deps
uv sync

# PyTorch cu128 (RTX 5070 Blackwell sm_120 호환)
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

# 환경 진단
uv run python scripts/doctor.py
```

### 2) 선택 의존성 (정확도 boost — 모두 graceful fallback)

```powershell
# SOTA 모델들 — CREPE bass(SOTA) + CREMA chord(170-class) + pyworld vocal pitch
uv pip install pyworld huggingface-hub
uv pip install crema
uv pip install crepe --no-build-isolation
uv pip install piano_transcription_inference     # 폴리포닉 피아노 ~80-85% F1

# Ollama 로컬 LLM (코드/섹션 LLM 검증 layer)
# bin/ollama/ 에 portable 배포되어 있음
.\bin\ollama\ollama.exe serve            # 백그라운드 — 새 창에서
.\bin\ollama\ollama.exe pull llama3.2:1b

# AUX classifier (sound-bank 자동 음색 추정)
uv pip install -e ".[aux_classifier]"
python scripts/build_aux_reference_db.py # 1회 ~30분, GPU 권장

# SOTA 분리 가중치 다운로드 (HuggingFace Hub, ~6 GB)
python scripts/fetch_sota_separator.py

# Phase B SaaS prep (선택)
uv pip install -e ".[saas]"
```

### 3) Backend 실행

```powershell
# uvicorn으로 FastAPI 서버 시작 (포트 7860, --reload 개발용)
uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 7860 --reload

# OpenAPI 문서: http://127.0.0.1:7860/docs
# 헬스체크:    http://127.0.0.1:7860/health
```

### 4) Frontend 실행

```powershell
cd frontend
npm install            # 최초 1회만
npm run dev            # Vite dev server (포트 5173, HMR 지원)

# 또는 production build
npm run build && npm run preview
```

- 개발용 URL: <http://localhost:5173>
- 프로덕션 build 결과물: `frontend/dist/`

### 5) 동시 실행 (편의)

별도 PowerShell 창 2개 권장:
- 창 1: backend uvicorn
- 창 2: `cd frontend && npm run dev`

또는 한 줄로 (PowerShell 5.1):
```powershell
Start-Process powershell -ArgumentList "-NoExit","-Command","uv run uvicorn backend.app.main:app --port 7860 --reload"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd frontend; npm run dev"
```

---

## 주요 기능

### 핵심 파이프라인
- **보컬 분리** — 4-model 앙상블 (MDX23C + BS-Roformer + htdemucs_ft + MelBand Kim v2) + karaoke postprocess + spectrogram-diff residual masking
- **키/템포 변환** — Rubber Band R3 finer + WORLD vocoder (±5 st 이상 보컬은 자동으로 World path)
- **코드 감지** — BTC + autochord + CREMA + functional-harmony re-rank + 로컬 LLM 검증 (4-stage)
- **섹션 감지** — all-in-one + SSM + 가사 반복 + LLM 검증
- **변호자 자동 감지** — 2/4, 3/4, 4/4, 5/4, 6/8, 7/8, 8/8, 9/8, 10/8, 11/8, 12/8 동시 후보 평가
- **가사 전사** — faster-whisper turbo + Silero-VAD + 도메인 priming (찬양 "하나님" vs 일반 "하느님")
- **AUX 음색 자동 추정** — CLAP + 5,178 reference vector (NSynth + Arachno SF2)

### 악보 / 출력
- **악보 자동 생성** — basic-pitch (vocal) / CREPE (bass) / piano_transcription_inference (piano polyphonic) / heuristic drums
- **Multi-page PDF** + 코드 + 가사 + AUX cue 통합 (Verovio engraving)
- **출력 포맷** — WAV/FLAC/AIFF/MP3/AAC × 44.1/48/88.2/96 kHz × 16/24/32f bit
- **고급 출력** — 5.1 surround / DSD64/128/256
- **마스터링** — LUFS 플랫폼 프리셋 (YouTube/Spotify/Apple/Tidal/Broadcast) + 3-band EQ
- **보컬 Auto-tune** — CREPE+WORLD scale-aware

### 라이브 / 워십
- **공연 모드** (`/perform/job/:id` 또는 `/perform/setlist/:id`) — 거대 코드 readout + 6-role 뷰 필터 (리더/보컬/키스/드럼/베이스/기타) + 9 instrument 이조 + 카운트인 + 텔레프롬프터 외부창
- **음성 제어** — 한국어/영어 (재생/정지/다음/이전/카운트인)
- **워십 모드** — 페달톤 패드 생성 + 곡-곡 segue (브릿지 키 자동)
- **세트리스트** — 키/BPM/모드 점프 자동 경고
- **녹음 + 채점** — 사용자 녹음 → CREPE 음정+타이밍 자동 grading

---

## 디렉터리

- `backend/app/` — FastAPI 애플리케이션
  - `api/` — jobs / setlists / notes / performance / formats / uploads
  - `pipeline/` — ingest / decode / separate / ensemble / polish / analyze / chords / sections / transform / lyrics / score / mastering / autotune / worship / spatial / aux_classifier
  - `core/` — jobs / paths / queue / events
  - `workers/orchestrator.py` — 단일 잡 end-to-end orchestrator
  - `db/` — Phase B SaaS prep (SQLAlchemy + Alembic, lazy-loaded)
- `frontend/src/` — React + Vite + Tailwind
  - `pages/` — Landing / Home / Job / LibraryPage / PerformanceView
  - `components/` — 30+ UI 컴포넌트
  - `lib/` — api / hooks (useJobHistory, useEta, useUndoStack, useVoiceControl, useKeyboardShortcuts) / transpose / setlistAnalyzer / roles
- `scripts/` — doctor / install_sota / fetch_sota_separator / build_aux_reference_db / build_kpop_section_dataset / probe_separator_hub / null_test
- `data/` — 작업 디렉터리 (gitignored). uploads / work / stems / output / models / logs
- `bin/` — 로컬 바이너리 (fluidsynth, rubberband-r3, ollama)
- `tests/` — pytest 테스트 + Playwright E2E
- `e2e/` — Playwright spec 파일들 (`frontend/e2e/`)

---

## 단축키 (공연 모드)

| 키 | 동작 |
|---|---|
| `Space` | 재생 / 일시정지 |
| `C` | 카운트인 1마디 후 재생 (박자 자동 감지) |
| `J` / `L` | 5초 뒤로 / 앞으로 |
| `N` / `P` | 다음 곡 / 이전 곡 (셋리스트) |
| `?` | 단축키 도움말 |
| `Esc` | 다이얼로그 닫기 |
| `Ctrl/Cmd+Z` | 에디터 undo |
| `Ctrl/Cmd+Shift+Z` | 에디터 redo |

---

## 테스트

```powershell
# 백엔드 smoke
uv run python -c "from backend.app.main import app; print('routes:', sum(1 for r in app.routes))"

# pytest (MUSDB18 회귀 등)
uv run pytest

# Frontend E2E (Playwright)
cd frontend
npx playwright install chromium  # 최초 1회
npx playwright test
```

---

## 전체 설계

세션별 진행 기록은 `~/.claude/projects/.../memory/project_ui_ux_pass.md` 참조.
초기 플랜: `C:\Users\Codelab\.claude\plans\glimmering-scribbling-plum.md`.

---

## 프로덕션 준비 상태 (2026-05-29)

GitHub: <https://github.com/youmin0523/Re-Chord_PJT>

### ✅ 코드/문서/검증 완료
- pytest **220 + 1 skipped** (no-GPU lane) / Vitest **27** / axe a11y **2/2**
- accuracy gate **synth + real-world(5곡 워십) PASSED** (chord_recall_transpose 1.0)
- 인증 (Supabase 카카오 OAuth + Phase B Alembic `b3c0d5e1f9a2_add_user_consents`)
- 챗봇 action 프로토콜 + 라이브 검증 (regenerate/loop/stop/한·영 locale)
- 법률 docs v1.0 시행 (`docs/legal/{terms,privacy,copyright}.md`)
- 운영 docs (`docs/operations/{deployment,monitoring,backup,secrets,db_setup}.md`)
- DB 셋업 자동화 (`scripts/setup_postgres.{ps1,sh}` — Supabase/Neon/RDS 호환)
- Phase B deploy 스캐폴드 (`deploy/{backend,frontend}.Dockerfile`, `nginx.conf` 보안 헤더 포함)
- k6 부하 테스트 + WS 재연결 회귀 + 챗봇 저작권 라이브 검증

### ⏳ 사용자 외부 작업 (인프라/계정)
출시 시점에 사용자가 직접 진행:

1. Supabase 프로젝트 생성 → URL / ANON_KEY / JWKS_URL 받기
2. `.\scripts\setup_postgres.ps1 -PgHost <SUPABASE_HOST>` 1회
3. `.env` (또는 secret manager)에 DATABASE_URL / VITE_SUPABASE_* 등록
4. 카카오 디벨로퍼스 비즈앱 → Supabase Auth provider 활성
5. R2 / Cloudflare 버킷 + API 토큰 (`AWS_*` env)
6. Cloud Run / Vercel 에 deploy/*.Dockerfile 연결
7. 도메인 / HTTPS / DNS
8. KISA 자가진단 (<https://privacy.go.kr>, 무료, 출시 직전 권장)
9. CPO·신고 채널 이메일 지정

### 🚫 의도적 미진행
- 결제(Toss) — 사용자 명시 제외 (출시 시 별도 의사결정)
- 변호사 검토 — 매출 1억 / 사용자 5천명 / 결제 / 해외 진출 도달 시점에 재검토 (`docs/legal/*` 의 "향후 변호사 검토 시 우선 확인사항" 메모 활용)
- CCLI / KOMCA 라이센싱 — 워십 가사 시드 DB 상업적 노출 시점
