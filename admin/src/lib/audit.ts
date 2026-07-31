import { supabase } from "./supabase";

export async function writeAuditLog(
  adminUsername: string,
  action: string,
  targetUserId?: string | null,
  details: Record<string, unknown> = {}
) {
  await supabase.from("admin_audit_log").insert({
    admin_username: adminUsername,
    action,
    target_user_id: targetUserId ?? null,
    details,
  });
}
