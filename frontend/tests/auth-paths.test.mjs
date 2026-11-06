// Run: npm test  (node --test; Node >= 22.18 strips the TypeScript types)
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  apiRequestPath,
  apiRootFrom,
  isAuthExemptApiPath,
  isPublicPagePath,
  loginHref,
  safeNextPath,
} from "../src/lib/auth-paths.ts";

test("safeNextPath keeps same-site relative paths", () => {
  assert.equal(safeNextPath("/projects/abc?tab=tendering#bids"), "/projects/abc?tab=tendering#bids");
  assert.equal(safeNextPath("/"), "/");
});

test("safeNextPath rejects open redirects", () => {
  for (const value of [
    null, undefined, "", "https://evil.example", "//evil.example/x", "/\\evil.example", "\\\\evil.example",
    "javascript:alert(1)", "evil.example", " //evil.example", "/%0d%0aLocation:evil", "/login", "/login?next=/x",
    "/\u0000x", "http:/evil.example",
  ]) {
    const result = safeNextPath(value);
    assert.ok(result === "/" || (result.startsWith("/") && !result.startsWith("//")), `${value} -> ${result}`);
    assert.ok(!result.includes("evil.example") || result.startsWith("/%"), `${value} -> ${result}`);
  }
  assert.equal(safeNextPath("https://evil.example"), "/");
  assert.equal(safeNextPath("//evil.example/x"), "/");
  assert.equal(safeNextPath("/\\evil.example"), "/");
  assert.equal(safeNextPath("/login?next=/x"), "/");
});

test("loginHref encodes a safe next and reason", () => {
  assert.equal(loginHref("/rentals?x=1", "expired"), "/login?next=%2Frentals%3Fx%3D1&reason=expired");
  assert.equal(loginHref("https://evil.example"), "/login");
  assert.equal(loginHref(null, "signed_out"), "/login?reason=signed_out");
});

test("public pages bypass the gate", () => {
  for (const path of ["/login", "/auth/callback", "/r/abc", "/rentals/reports/tok123"]) assert.ok(isPublicPagePath(path), path);
  for (const path of ["/", "/rentals", "/rentals/reports", "/projects/1", "/loginx"]) assert.ok(!isPublicPagePath(path), path);
});

test("apiRequestPath recognises backend calls only", () => {
  const origin = "https://officehub.n10z.ca";
  assert.equal(apiRootFrom("/backend-api/api/v1/"), "/backend-api");
  assert.equal(apiRootFrom(undefined), "/backend-api");
  assert.equal(apiRequestPath("/backend-api/api/v1/projects", "/backend-api", origin), "/api/v1/projects");
  assert.equal(apiRequestPath(`${origin}/backend-api/api/auth/session`, "/backend-api", origin), "/api/auth/session");
  assert.equal(apiRequestPath("/api/change-orders/1", "/backend-api", origin), "/api/change-orders/1");
  assert.equal(apiRequestPath("http://localhost:8000/api/v1/x", "http://localhost:8000", origin), "/api/v1/x");
  assert.equal(apiRequestPath("https://maps.googleapis.com/api/js", "/backend-api", origin), null);
  assert.equal(apiRequestPath("/backend-apix/api/v1", "/backend-api", origin), null);
  assert.equal(apiRequestPath("/_next/static/chunk.js", "/backend-api", origin), null);
});

test("auth and public API 401s never redirect", () => {
  assert.ok(isAuthExemptApiPath("/api/auth/session"));
  assert.ok(isAuthExemptApiPath("/api/public/intake/x"));
  assert.ok(isAuthExemptApiPath("/api/rentals/reports/public/t"));
  assert.ok(!isAuthExemptApiPath("/api/v1/projects"));
});
