/**
 * Seeds the first admin user from env vars if the admin_users table is empty.
 * Call this at server startup (e.g. in the Next.js root layout or a route handler).
 */
import bcrypt from "bcryptjs";
import { supabase } from "./supabase";

let seeded = false;

export async function seedAdminIfNeeded() {
  if (seeded) return;
  seeded = true;

  const username = process.env.ADMIN_USERNAME;
  const password = process.env.ADMIN_PASSWORD;
  if (!username || !password) return;

  const { data: existing } = await supabase
    .from("admin_users")
    .select("id")
    .eq("username", username)
    .single();

  if (existing) return; // Already seeded

  const hash = await bcrypt.hash(password, 12);
  await supabase.from("admin_users").insert({ username, password_hash: hash });
  console.log(`[seed] Admin user "${username}" created.`);
}
