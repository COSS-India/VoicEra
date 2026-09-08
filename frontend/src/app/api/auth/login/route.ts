import { NextRequest, NextResponse } from "next/server";

interface LoginBody {
  username?: string;
  password?: string;
}

// Mock auth store — this is a UI-kit demo, not wired to a real database.
const MOCK_USER = {
  id: "u_roopan",
  name: "Roopan S",
  username: "roopan",
  email: "roopan@cossindia.org",
  org: "COSS India",
  role: "Owner",
};

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as LoginBody;
  const { username, password } = body;

  if (!username || !password) {
    return NextResponse.json(
      { ok: false, error: "Username and password are required." },
      { status: 400 },
    );
  }

  if (password.length < 4) {
    return NextResponse.json(
      { ok: false, error: "Invalid username or password." },
      { status: 401 },
    );
  }

  return NextResponse.json({
    ok: true,
    user: { ...MOCK_USER, username },
    token: `mock-token-${Buffer.from(username).toString("base64url")}`,
  });
}
