// k6 load test (M9.03): the three interactive reads, through nginx.
//
//   docker run --rm --network verita_default -v "$PWD/perf:/perf" \
//     -e BASE=http://web:8080 -e PASSWORD=... grafana/k6:1.3.0 run /perf/load.js
//
// Default scenario — 50 analysts working: each pauses 1–3 s between actions, as a person
// reading a screen does. Acceptance: p95 < 300 ms per endpoint, < 1% errors.
// STRESS=1 — the same 50 users with no pauses: a saturation test that reports the maximum
// throughput and the latency at it; it has no latency threshold (only errors < 1%).
import http from "k6/http";
import { check, sleep } from "k6";

const STRESS = __ENV.STRESS === "1";

const BASE = __ENV.BASE || "http://web:8080";
const API = `${BASE}/api/v1`;

export const options = {
  scenarios: {
    analysts: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "15s", target: 50 },
        { duration: "60s", target: 50 },
        { duration: "10s", target: 0 },
      ],
    },
  },
  thresholds: STRESS
    ? { http_req_failed: ["rate<0.01"] }
    : {
        "http_req_duration{endpoint:queue}": ["p(95)<300"],
        "http_req_duration{endpoint:subgraph}": ["p(95)<300"],
        "http_req_duration{endpoint:plan}": ["p(95)<300"],
        http_req_failed: ["rate<0.01"],
      },
};

export function setup() {
  const res = http.post(`${API}/auth/login`, JSON.stringify({ username: "validator", password: __ENV.PASSWORD }), {
    headers: { "Content-Type": "application/json" },
  });
  check(res, { "signed in": (r) => r.status === 200 });
  const cookie = Object.entries(res.cookies)
    .map(([name, values]) => `${name}=${values[0].value}`)
    .join("; ");
  const headers = { Cookie: cookie };
  const queue = http.get(`${API}/alerts?limit=100`, { headers }).json();
  const meta = http.get(`${API}/capacity/meta`, { headers }).json();
  return { headers, ids: queue.items.map((a) => a.id), days: meta.days };
}

export default function (data) {
  const params = (endpoint) => ({ headers: data.headers, tags: { endpoint } });
  const id = data.ids[Math.floor(Math.random() * data.ids.length)];
  const day = data.days[Math.floor(Math.random() * Math.min(data.days.length, 3))];
  const analysts = 1 + Math.floor(Math.random() * 20);

  const think = () => {
    if (!STRESS) sleep(1 + Math.random() * 2);
  };
  check(http.get(`${API}/alerts?limit=50`, params("queue")), { queue: (r) => r.status === 200 });
  think();
  check(http.get(`${API}/alerts/${id}/subgraph`, params("subgraph")), { subgraph: (r) => r.status === 200 });
  think();
  check(http.get(`${API}/capacity/plan?date=${day}&analysts=${analysts}`, params("plan")), {
    plan: (r) => r.status === 200,
  });
  think();
}
