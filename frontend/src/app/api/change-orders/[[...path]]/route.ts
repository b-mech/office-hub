import type { NextRequest } from "next/server";

function backendChangeOrderUrl(request: NextRequest, path: string[]): string {
  const publicApiBase = process.env.NEXT_PUBLIC_API_URL;
  const configuredBase = (
    process.env.OFFICE_HUB_BACKEND_URL ||
    (publicApiBase?.startsWith("http://") || publicApiBase?.startsWith("https://")
      ? publicApiBase
      : "http://127.0.0.1:8000")
  ).replace(/\/+$/, "");
  const apiBase = configuredBase.endsWith("/api/v1")
    ? configuredBase
    : `${configuredBase}/api/v1`;
  const suffix = path.length > 0 ? `/${path.map(encodeURIComponent).join("/")}` : "";
  return `${apiBase}/change-orders${suffix}${request.nextUrl.search}`;
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path?: string[] }> },
): Promise<Response> {
  const apiKey = process.env.OFFICE_HUB_API_KEY;
  if (!apiKey) {
    return Response.json(
      { detail: "Office Hub server authentication is not configured" },
      { status: 500 },
    );
  }

  const { path = [] } = await context.params;
  const headers = new Headers({
    "X-API-Key": apiKey,
  });
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
  const upstream = await fetch(backendChangeOrderUrl(request, path), {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });

  const responseHeaders = new Headers();
  for (const headerName of ["content-type", "content-disposition", "content-length"]) {
    const value = upstream.headers.get(headerName);
    if (value) {
      responseHeaders.set(headerName, value);
    }
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
