import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { supabase } from "@/lib/supabase";
import { writeAuditLog } from "@/lib/audit";

function generateCode(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let code = "PULSE-";
  for (let i = 0; i < 6; i++) {
    code += chars[Math.floor(Math.random() * chars.length)];
  }
  return code;
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions);
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json();
  const admin = session.user?.name ?? "admin";

  if (body.action === "generate") {
    const balance = parseFloat(body.balance) || 5;
    const code = generateCode();
    await supabase.from("invitation_codes").insert({
      code,
      starting_balance_sol: balance,
      status: "unused",
    });
    await writeAuditLog(admin, "generate_code", null, { code, balance });
    return NextResponse.json({ ok: true, code });
  }

  if (body.action === "revoke") {
    const { id } = body;
    await supabase
      .from("invitation_codes")
      .update({ status: "revoked" })
      .eq("id", id)
      .eq("status", "unused");
    await writeAuditLog(admin, "revoke_code", null, { code_id: id });
    return NextResponse.json({ ok: true });
  }

  return NextResponse.json({ error: "Unknown action" }, { status: 400 });
}
