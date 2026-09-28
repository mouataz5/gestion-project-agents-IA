import { describe, expect, it } from "vitest";

import {
  ProxyPathError,
  buildBackendUrl,
  forwardedRequestHeaders,
  forwardedResponseHeaders,
  maxBodyBytes,
} from "./proxy";

const BASE = "http://backend:8000";
const PREFIX = "/api/v1";

describe("buildBackendUrl", () => {
  it("maps path segments under the API prefix", () => {
    const url = buildBackendUrl(BASE, PREFIX, ["runs", "diagnostic"], "");
    expect(url.toString()).toBe("http://backend:8000/api/v1/runs/diagnostic");
  });

  it("preserves the query string", () => {
    const url = buildBackendUrl(BASE, PREFIX, ["runs"], "?limit=5&status=FAILED");
    expect(url.toString()).toBe("http://backend:8000/api/v1/runs?limit=5&status=FAILED");
  });

  it("tolerates a trailing slash on the base URL", () => {
    const url = buildBackendUrl("http://localhost:8000/", PREFIX, ["system", "info"], "");
    expect(url.toString()).toBe("http://localhost:8000/api/v1/system/info");
  });

  it.each([
    [[]],
    [[".."]],
    [["runs", ".."]],
    [["."]],
    [[""]],
    [["runs/../../admin"]],
    [["a\\b"]],
    [["http:", "", "evil.test"]],
    [["runs", "%2e%2e"]],
    [["<script>"]],
  ])("rejects unsafe segments %j", (segments) => {
    expect(() => buildBackendUrl(BASE, PREFIX, segments, "")).toThrow(ProxyPathError);
  });

  it("rejects a non-http backend URL", () => {
    expect(() => buildBackendUrl("file:///etc", PREFIX, ["runs"], "")).toThrow(ProxyPathError);
  });
});

describe("forwarded headers", () => {
  it("forwards only allow-listed request headers and injects the API token", () => {
    const incoming = new Headers({
      "content-type": "application/json",
      accept: "application/json",
      "x-request-id": "trace-1",
      cookie: "session=secret",
      authorization: "Bearer from-the-browser",
      host: "frontend:3000",
    });

    const headers = forwardedRequestHeaders(incoming, "server-token");

    expect(headers.get("authorization")).toBe("Bearer server-token");
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("x-request-id")).toBe("trace-1");
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("host")).toBeNull();
  });

  it("never forwards browser credentials when no server token is configured", () => {
    const headers = forwardedRequestHeaders(new Headers({ authorization: "Bearer x" }), undefined);
    expect(headers.get("authorization")).toBeNull();
  });

  it("returns only safe response headers", () => {
    const headers = forwardedResponseHeaders(
      new Headers({
        "content-type": "application/json",
        "x-request-id": "abc",
        "set-cookie": "a=b",
        server: "uvicorn",
      }),
    );

    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("x-request-id")).toBe("abc");
    expect(headers.get("set-cookie")).toBeNull();
    expect(headers.get("server")).toBeNull();
    expect(headers.get("cache-control")).toBe("no-store");
  });

  it("forwards content-disposition so file downloads keep their name", () => {
    const headers = forwardedResponseHeaders(
      new Headers({ "content-disposition": 'attachment; filename="cv.docx"' }),
    );
    expect(headers.get("content-disposition")).toBe('attachment; filename="cv.docx"');
  });
});

describe("maxBodyBytes", () => {
  it("allows the configured upload size plus multipart overhead", () => {
    expect(maxBodyBytes(undefined)).toBe(6 * 1024 * 1024);
    expect(maxBodyBytes("10")).toBe(11 * 1024 * 1024);
  });

  it.each(["", "abc", "0", "-3"])("falls back to the default for %j", (value) => {
    expect(maxBodyBytes(value)).toBe(6 * 1024 * 1024);
  });
});
