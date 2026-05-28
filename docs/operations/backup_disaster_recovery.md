# 백업 / 재해 복구 (Disaster Recovery)

운영 데이터 손실을 막고, 사고 시 RPO/RTO 목표를 맞추기 위한 백업 정책.
대상은 **Postgres (Job 메타·세션·동의 로그·악보 메타)**, **Object
Storage (R2/S3 — 사용자 업로드 + 분리 결과물)**, **앱 코드 (GitHub
이미 됨)** 세 가지.

---

## 0. 목표 (RPO / RTO)

| 자원 | RPO (허용 데이터 손실) | RTO (복구까지 시간) |
|------|------------------------|---------------------|
| Postgres (사용자 메타·동의) | **15분** | 1시간 |
| Postgres (Job 분석 결과) | 24시간 | 4시간 |
| R2 객체 (원본 음원·분리 결과) | 0 (versioning) | 즉시 (versioning rollback) |
| 앱 코드 | 0 (GitHub) | 즉시 |
| 모델 가중치 | 24시간 (S3 + HF Hub 둘 다 보관) | 1시간 |

RPO < RTO 가 일반적. 예배 시즌 (주말) 에는 RTO 단축 운영 (oncall 강화).

---

## 1. Postgres 백업

### 1.1 관리형 DB의 자동 백업 (Supabase/Neon/RDS)

| 제공자 | 자동 백업 | 보관 | 활성화 방법 |
|--------|-----------|------|-------------|
| Supabase | 매일 (PITR Pro 플랜) | 7-30일 | Dashboard → Database → Backups |
| Neon | 시간당 (branching) | 24시간 (Free) / 7일 (Paid) | 기본 활성 |
| AWS RDS | 매일 + WAL | 7-35일 | Console → Backup retention |

**Phase B 출시 첫날 반드시 확인할 것**:
- 자동 백업이 활성화되어 있는지
- Point-in-time recovery (PITR) 가능한지
- 백업 보관 기간 ≥ 7일

### 1.2 수동 스냅샷 스크립트 (긴급 / 마이그레이션 전)

`scripts/backup_postgres.sh` 로 자체 dump 생성. 자동 백업이 못 미치는
"방금 전 직전" 상태가 필요할 때 (스키마 변경 직전 등):

```bash
./scripts/backup_postgres.sh                                    # default ./backups/
DUMP_DIR=/mnt/backups ./scripts/backup_postgres.sh             # custom path
```

(파일은 §3 참조)

### 1.3 복구 절차

**관리형 DB PITR**:

1. 사고 발생 시각 파악 (Sentry / 알람 타임스탬프)
2. 콘솔 → Backups → "Restore to point in time" → 사고 직전 시각 선택
3. 새 인스턴스에 복원
4. 검증: 핵심 쿼리 (`SELECT COUNT(*) FROM jobs`, 동의 로그 등)
5. `DATABASE_URL` 을 신규 인스턴스로 교체 → Cloud Run rolling restart
6. 사용자 영향 공지 (변경 사항 안내)

**수동 dump 복원**:

```bash
gunzip -c backups/2026-05-28_03-00.sql.gz | \
  psql -h <NEW_HOST> -U <ADMIN> -d <NEW_DB>
```

---

## 2. Object Storage (R2 / S3)

### 2.1 Versioning 활성화

```bash
# Cloudflare R2
wrangler r2 bucket versioning enable rechord-prod

# AWS S3
aws s3api put-bucket-versioning --bucket rechord-prod \
    --versioning-configuration Status=Enabled
```

versioning 활성화 시:
- 같은 키에 PUT 하면 새 version 생성 (이전 version 보존)
- DELETE는 "delete marker" 추가 (영구 삭제 아님)
- 비용 ↑ — 오래된 version은 lifecycle policy로 30일 후 삭제

### 2.2 Lifecycle policy

```jsonc
// s3-lifecycle.json — 30일 지난 noncurrent version 자동 삭제
{
  "Rules": [
    {
      "ID": "expire-noncurrent-30d",
      "Status": "Enabled",
      "NoncurrentVersionExpiration": { "NoncurrentDays": 30 }
    }
  ]
}
```

### 2.3 복구 절차

```bash
# 특정 객체의 모든 version 보기
aws s3api list-object-versions --bucket rechord-prod --prefix jobs/abc123/

# 특정 version으로 복구 (delete marker 제거)
aws s3api delete-object --bucket rechord-prod \
    --key jobs/abc123/instrumental_final.wav \
    --version-id <DELETE_MARKER_VERSION_ID>
```

---

## 3. 모델 가중치 백업

- HuggingFace Hub: SOTA 모델은 원본 hub에 있음 — `scripts/fetch_sota_separator.py`
  로 언제든 재다운로드 가능 → 사실 백업 불필요
- 자체 학습 모델 (있다면): R2 bucket 별도 `rechord-models/` prefix에
  versioning 활성화로 보관

---

## 4. 사용자 데이터 보존 / 파기 (PIPA)

[`docs/legal/privacy_policy.md`](../legal/privacy_policy.md) §3 의 보존
기간을 자동화:

```python
# scripts/purge_expired_data.py (예정 — 일일 cron)
# 30일 지난 jobs.artifacts → R2 delete + jobs row update
# 1년 지난 jobs row → DELETE (audit 로그만 남김)
# 1년 지난 chat messages → DELETE (사용자 미삭제 케이스)
# 3개월 지난 access logs → DELETE
```

이 스크립트는 일일 cron으로 돌리고, 실행 결과는 `audit_log` 테이블에
기록 (compliance 입증 자료).

---

## 5. 복구 훈련 (Game Day)

분기 1회 권장:

1. staging 환경에서 의도적으로 DB 인스턴스 종료
2. PITR 절차 따라 복구
3. RTO 측정 (목표 1시간)
4. 발견된 절차 누락 → 본 문서 갱신

또한 모든 운영자가 절차 숙지 (혼자만 아는 단계가 있으면 SEV-1 시
복구 지연).

---

## 6. 백업 모니터링

자동 백업이 *조용히* 실패하는 게 가장 위험:

- 관리형 DB: 콘솔에서 "Last successful backup" 시각 알람
- 수동 dump (cron): 결과 파일 크기 alert (전일 ±10% 벗어나면 #pager)
- R2: versioning 활성화 status 주간 자동 확인

```bash
# scripts/verify_backup_freshness.sh — cron이 마지막 dump 시각 점검
LAST=$(ls -t backups/*.sql.gz | head -1)
AGE_SEC=$(( $(date +%s) - $(stat -c %Y "$LAST") ))
if (( AGE_SEC > 86400 )); then
    echo "BACKUP STALE: $LAST is $AGE_SEC seconds old" >&2
    exit 1
fi
```

알람 채널은 `#pager` (즉시 대응).
