import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { PROTECTED_PREFIXES, ROLE_REDIRECT } from "@/lib/constants";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix));

  if (!isProtected) return NextResponse.next();

  // Read the role cookie set by the auth store on login.
  const role = request.cookies.get("att_role")?.value;

  if (!role) {
    // Not authenticated — redirect to login, preserving the intended URL.
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Check if the user is trying to access the correct portal for their role.
  const correctBase = ROLE_REDIRECT[role]?.split("/")[1]; // e.g. "admin"
  if (correctBase && !pathname.startsWith(`/${correctBase}`)) {
    return NextResponse.redirect(new URL(ROLE_REDIRECT[role] ?? "/login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/admin/:path*",
    "/hr/:path*",
    "/manager/:path*",
    "/employee/:path*",
  ],
};
