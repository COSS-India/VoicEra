import { NextRequest, NextResponse } from "next/server";

interface SignupBody {
  name?: string;
  username?: string;
  password?: string;
}

// Mock auth store — this is a UI-kit demo, not wired to a real database.
const RESERVED_USERNAMES = new Set(["admin", "root", "voicera"]);

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as SignupBody;
  const { name, username, password } = body;

  if (!name || !username || !password) {
    return NextResponse.json(
      { ok: false, error: "Name, username, and password are required." },
      { status: 400 },
    );
  }

  if (password.length < 4) {
    return NextResponse.json(
      { ok: false, error: "Password must be at least 4 characters." },
      { status: 400 },
    );
  }

  if (RESERVED_USERNAMES.has(username.toLowerCase())) {
    return NextResponse.json(
      { ok: false, error: "That username is already taken." },
      { status: 409 },
    );
  }

  return NextResponse.json(
    {
      ok: true,
      user: {
        id: `u_${username.toLowerCase()}`,
        name,
        username,
        email: `${username}@cossindia.org`,
        org: "COSS India",
        role: "Owner",
      },
      token: `mock-token-${Buffer.from(username).toString("base64url")}`,
    },
    { status: 201 },
  );
}
