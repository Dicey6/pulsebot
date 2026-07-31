import { supabase } from "@/lib/supabase";
import Link from "next/link";
import UserActions from "./UserActions";

async function getUsers(search?: string) {
  let query = supabase
    .from("users")
    .select("id, telegram_id, telegram_username, sol_balance, status, created_at, last_active_at")
    .order("last_active_at", { ascending: false });

  if (search) {
    query = query.or(
      `telegram_username.ilike.%${search}%,telegram_id.eq.${isNaN(Number(search)) ? 0 : search}`
    );
  }

  const { data } = await query;
  return data || [];
}

async function getOpenPositionCounts(): Promise<Record<string, number>> {
  const { data } = await supabase
    .from("positions")
    .select("user_id")
    .eq("status", "open");
  const counts: Record<string, number> = {};
  for (const row of data || []) {
    counts[row.user_id] = (counts[row.user_id] || 0) + 1;
  }
  return counts;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-green-900/40 text-green-400",
    paused: "bg-yellow-900/40 text-yellow-400",
    restricted: "bg-orange-900/40 text-orange-400",
    banned: "bg-red-900/40 text-red-400",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[status] ?? "text-gray-400"}`}>
      {status}
    </span>
  );
}

export default async function UsersPage({
  searchParams,
}: {
  searchParams: { q?: string };
}) {
  const [users, positionCounts] = await Promise.all([
    getUsers(searchParams.q),
    getOpenPositionCounts(),
  ]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Users</h1>
        <form>
          <input
            name="q"
            defaultValue={searchParams.q}
            placeholder="Search username or Telegram ID…"
            className="bg-pulse-dark border border-pulse-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-pulse-purple w-64"
          />
        </form>
      </div>

      <div className="bg-pulse-card border border-pulse-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-pulse-border">
            <tr className="text-gray-500">
              <th className="text-left px-4 py-3">User</th>
              <th className="text-left px-4 py-3">Telegram ID</th>
              <th className="text-left px-4 py-3">Balance</th>
              <th className="text-left px-4 py-3">Positions</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Joined</th>
              <th className="text-left px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u: any) => (
              <tr key={u.id} className="border-b border-pulse-border/50 hover:bg-pulse-border/20">
                <td className="px-4 py-3">
                  <Link
                    href={`/dashboard/users/${u.id}`}
                    className="text-pulse-purple-light hover:underline"
                  >
                    @{u.telegram_username}
                  </Link>
                </td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{u.telegram_id}</td>
                <td className="px-4 py-3 text-white">{parseFloat(u.sol_balance).toFixed(4)} SOL</td>
                <td className="px-4 py-3 text-gray-300">{positionCounts[u.id] || 0}/4</td>
                <td className="px-4 py-3">
                  <StatusBadge status={u.status} />
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {new Date(u.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3">
                  <UserActions userId={u.id} currentStatus={u.status} />
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
