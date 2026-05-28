# 가입 동의 UI 사양 (Phase B 인증 도입 시)

> **상태**: 설계 사양 / 미구현. Phase B 인증 (Supabase + 카카오) 도입
> 시 이 사양에 따라 컴포넌트를 추가합니다. 결제(Toss)는 별도 흐름이라
> 본 문서에서 제외합니다.

베타 단계는 게스트 모드이므로 가입 화면이 없습니다. 정식 출시 시 인증
flow에 본 사양의 동의 UI를 끼워 넣습니다.

---

## 1. 노출 조건

| 조건 | 가입 화면 노출 | 동의 재요청 |
|------|----------------|-------------|
| 신규 가입 (카카오/이메일) | **필수** | — |
| 약관·개인정보 개정 후 첫 로그인 | **필수** | 변경 차이점만 강조 |
| 기존 사용자가 콘솔에서 동의 회수 | "처리정지" 모드 → 재동의 시 활성화 | — |
| 만 14세 미만 가입 시도 | "법정대리인 동의 필요" 차단 화면 | — |

---

## 2. 컴포넌트 구조

```
<SignupConsent>
  ├ <ConsentSection required title="서비스 이용약관" doc="/legal/terms" />
  ├ <ConsentSection required title="개인정보 수집·이용 동의" doc="/legal/privacy" />
  ├ <ConsentSection required title="개인정보의 국외이전 동의" doc="/legal/privacy#section-4" />
  ├ <ConsentSection title="저작권 책임 자가 진술" doc="/legal/copyright" />
  ├ <ConsentSection optional title="마케팅 정보 수신" doc="/legal/marketing" />
  └ <AgeConfirm minAge={14} />
```

각 `<ConsentSection>` 은:

- 체크박스 + 약관 제목 + 상세보기 버튼 (모달 또는 새 탭)
- `required=true` 이면 미체크 시 [동의하고 가입] 비활성화
- `optional=true` 는 별도 묶음으로 분리 (필수 동의와 시각 구분)

`<AgeConfirm>`: 사용자가 직접 만나이를 입력. 14세 미만이면 법정대리인
이메일 인증으로 분기.

---

## 3. 동의 항목 (한국 PIPA 기준)

### 필수 (5)

| # | 항목 | 근거 |
|---|------|------|
| 1 | 서비스 이용약관 동의 | 정보통신망법 §22 / 약관규제법 |
| 2 | 개인정보 수집·이용 동의 (서비스 제공 목적) | PIPA §15, §17 |
| 3 | 개인정보 국외이전 동의 (OpenAI/Sentry 등) | PIPA §28-8 |
| 4 | 만 14세 이상 확인 | PIPA §39-3 / 망법 §31 |
| 5 | 저작권 책임 자가 진술 (업로드 음원의 권리 보유) | 약관 4조 1항 |

### 선택 (1)

| # | 항목 |
|---|------|
| 1 | 마케팅 정보 수신 동의 (이메일·푸시) |

### 미수집 (명시)

- 결제 정보 (Toss 등 PG사 직접 처리, 회사는 거래ID만 보관)
- 정밀 위치 정보
- 주민등록번호

---

## 4. 화면 흐름 (Step-by-Step)

```
┌─────────────────────────────────────────────────┐
│ STEP 1.  로그인 방법 선택                       │
│   ◯ 카카오로 시작                                │
│   ◯ 이메일로 시작                                │
└─────────────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────────────┐
│ STEP 2.  연령 확인                              │
│   생년월일: [____] 년 [__]월 [__]일             │
│                                                 │
│   * 만 14세 미만은 법정대리인 동의가 필요합니다 │
└─────────────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────────────┐
│ STEP 3.  필수 동의 (5)                          │
│   ☐ [필수] 서비스 이용약관 동의       [상세 ↗] │
│   ☐ [필수] 개인정보 수집·이용 동의    [상세 ↗] │
│   ☐ [필수] 개인정보 국외이전 동의     [상세 ↗] │
│   ☐ [필수] 14세 이상 확인                       │
│   ☐ [필수] 저작권 책임 자가 진술      [상세 ↗] │
│                                                 │
│   STEP 4.  선택 동의                            │
│   ☐ [선택] 마케팅 정보 수신                     │
│                                                 │
│   [ 모두 동의 ]   [ 동의하고 가입 (비활성화) ]  │
└─────────────────────────────────────────────────┘
```

---

## 5. 백엔드 저장 모델

`user_consents` 테이블 신설 (Alembic 마이그레이션 필요):

```sql
CREATE TABLE user_consents (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    consent_type    TEXT NOT NULL,           -- "tos" | "privacy" | "intl_transfer" | "age_14" | "copyright_self" | "marketing"
    version         TEXT NOT NULL,           -- "2026-05-28-v0.1"  (각 약관 파일의 시행일 + 버전)
    granted         BOOLEAN NOT NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ,
    ip_address      INET,                    -- 동의 시점 IP (PIPA 입증)
    user_agent      TEXT
);
CREATE INDEX ON user_consents(user_id, consent_type, version);
```

각 동의는 별도 row. 약관이 개정되면 새 version row를 만들고 사용자가
다시 체크해야 처리 계속 가능.

---

## 6. API 엔드포인트 (예정)

```
POST /api/consents
  body: { consent_type, version, granted: true }
  effect: row 삽입 (idempotent on (user_id, consent_type, version))

GET /api/consents/me
  → 사용자가 현재 동의 중인 항목 + 버전 + 일시 (마이페이지에 표시)

DELETE /api/consents/{consent_type}
  → revoked_at 채우고 처리정지 모드 전환 (필수 항목은 서비스 이용 일시 정지)
```

---

## 7. 변경 (re-consent) 흐름

약관 시행일자가 바뀌면:

1. `versions` 테이블에 새 row + 변경 요약 텍스트
2. 모든 로그인 사용자에게 다음 접속 시 "변경 사항 안내" 모달
3. 변경된 필수 동의 항목을 다시 체크해야 진행 가능
4. 거부 시 → "서비스 이용 중단 / 데이터 다운로드 옵션" 제공 (PIPA §22 유사 절차)

---

## 8. 접근성 / UX 디테일

- 체크박스는 라벨 클릭으로도 토글 (큰 터치 영역)
- 약관 본문은 별도 페이지(`/legal/...`)에서 markdown 렌더 — `docs/legal/` 의 .md 파일 그대로 노출
- 키보드 내비게이션 — Tab으로 모든 체크박스 도달
- 색상만으로 [필수] 표시 X (텍스트 라벨 + aria-required)
- 모바일 단일 컬럼 / 데스크탑은 좌측 텍스트 우측 약관 미리보기 (선택)
- 변환 페이지(/app) 첫 진입 사용자에겐 "베타 무료 — 가입 없이 시도하기" 옵션 유지

---

## 9. 구현 체크리스트 (Phase B 진입 시)

- [ ] `frontend/src/components/auth/SignupConsent.jsx` 신규
- [ ] `frontend/src/components/auth/ConsentSection.jsx` 신규
- [ ] `frontend/src/components/auth/AgeConfirm.jsx` 신규
- [ ] `frontend/src/pages/Signup.jsx` 라우트
- [ ] `backend/app/api/consents.py` 신규 (CRUD)
- [ ] Alembic 마이그레이션: `user_consents` 테이블
- [ ] `tests/test_consents.py` — 필수 동의 누락 시 가입 거부
- [ ] e2e: 가입 → /app 진입까지 골든 path Playwright spec
- [ ] 약관 페이지 라우트: `/legal/terms`, `/legal/privacy`, `/legal/copyright`
  (`docs/legal/*.md` 를 react-markdown으로 렌더)
- [ ] 변경 안내 모달 컴포넌트
- [ ] 마이페이지 동의 현황 위젯

---

## 10. 외부 의존성

- Supabase Auth: 카카오 OAuth provider 설정 → redirect URI 등록
- 카카오 디벨로퍼스: 비즈 앱 등록 (개인정보 수집 항목: 이메일·닉네임만)
- PIPA 사전 자가 진단 (개인정보영향평가 — 필요한 규모 도달 시)
