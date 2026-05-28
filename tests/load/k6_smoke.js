// Re:Chord 부하 테스트 — k6 smoke run.
//
// 가벼운 동시 사용자 시나리오로 API의 무거운 경로를 두드려 본다.
// 실제 잡 제출은 GPU 점유를 시키므로 이 스크립트는 *읽기 위주* (formats /
// health / chat session 생성)만 부하한다. 진짜 잡 처리 부하는 별도
// "soak" 스크립트로 분리해야 한다 (k6_soak.js, 이번에 미작성).
//
// 실행:
//   k6 run --vus 10 --duration 60s tests/load/k6_smoke.js
//   k6 run --vus 50 --duration 5m  tests/load/k6_smoke.js   # 짧은 spike
//
// 환경변수:
//   K6_BASE_URL  대상 API base URL (default http://127.0.0.1:7860)

import http from "k6/http";
import { check, sleep, group } from "k6";

const BASE = __ENV.K6_BASE_URL || "http://127.0.0.1:7860";

export const options = {
  // 단계적 증가로 traffic ramping 흉내. 임계값을 넘으면 즉시 fail.
  stages: [
    { duration: "10s", target: 5 },     // ramp up
    { duration: "30s", target: 20 },    // sustain
    { duration: "10s", target: 0 },     // ramp down
  ],
  thresholds: {
    // 95퍼센타일 응답 시간 ≤ 600ms (health/formats 같은 가벼운 경로 기준)
    http_req_duration: ["p(95)<600"],
    // 실패율 1% 미만
    http_req_failed: ["rate<0.01"],
  },
};

export default function () {
  group("health", () => {
    const r = http.get(`${BASE}/health`);
    check(r, {
      "health 200": (res) => res.status === 200,
      "health ok": (res) => res.json("status") === "ok",
    });
  });

  group("formats", () => {
    const r = http.get(`${BASE}/formats`);
    check(r, {
      "formats 200": (res) => res.status === 200,
      "has modes":   (res) => Array.isArray(res.json("modes")),
    });
  });

  group("chat session create", () => {
    const r = http.post(
      `${BASE}/chat/sessions`,
      JSON.stringify({}),
      { headers: { "Content-Type": "application/json" } },
    );
    check(r, {
      "chat 200": (res) => res.status === 200,
      "has id":   (res) => typeof res.json("id") === "string",
    });
  });

  // 부하 사이 짧은 대기 — burst 흉내가 아니라 자연스러운 사용자 페이스
  sleep(1);
}
