import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { supabase } from "@/lib/supabase";
import { writeAuditLog } from "@/lib/audit";

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  const session = await getServerSession(authOptions);
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const body = await req.json();
  const { action } = body;
  const userId = params.id;
  const admin = session.user?.name ?? "admin";

  switch (action) {
    case "pause":
    case "restrict":
    case "ban":
    case "activate": {
      const statusMap: Record<string, string> = {
        pause: "paused",
        restrict: "restricted",
        ban: "banned",
        activate: "active",
      };
      await supabase
        .from("users")
        .update({ status: statusMap[action] })
        .eq("id", userId);
      await writeAuditLog(admin, action, userId, {});
      break;
    }

    case "set_balance": {
      const balance = parseFloat(body.balance);
      if (isNaN(balance)) return NextResponse.json({ error: "Invalid balance" }, { status: 400 });
      await supabase.from("users").update({ sol_balance: balance }).eq("id", userId);
      await writeAuditLog(admin, "set_balance", userId, { balance });
      break;
    }

    case "force_close_all": {
      const now = new Date().toISOString();
      await supabase
        .from("positions")
        .update({ status: "closed", closed_at: now, amount_tokens: 0 })
        .eq("user_id", userId)
        .eq("status", "open");
      await writeAuditLog(admin, "force_close_position", userId, { all: true });
      break;
    }

    default:
      return NextResponse.json({ error: "Unknown action" }, { status: 400 });
  }

  return NextResponse.json({ ok: true });
}
