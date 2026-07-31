import { supabase } from "@/lib/supabase";

async function getStats() {
  const [{ count: totalUsers }, { count: totalPositions }, { data: recentUsers }] =
    await Promise.all([
      supabase.from("users").select("*", { count: "exact", head: true }),
      supabase
        .from("positions")
        .select("*", { count: "exact", head: true })
        .eq("status", "open"),
      supabase
        .from("users")
        .select("telegram_username, sol_balance, last_active_at, status")
        .order("last_active_at", { ascending: false })
        .limit(10),
    ]);

  // Total SOL in play (sum across all open positions by user balances)
  const { data: balances } = await supabase
    .from("users")
    .select("sol_balance")
    .eq("status", "active");

  const totalSol = (balances || []).reduce(
    (sum, u) => sum + parseFloat(u.sol_balance || "0"),
    0
  );

  return { totalUsers: totalUsers ?? 0, totalPositions: totalPositions ?? 0, totalSol, recentUsers: recentUsers ?? [] };
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="bg-pulse-card border border-pulse-border rounded-xl p-5">
      <p className="text-sm text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-gray-600 mt-1">{sub}</p>}
    </div>
  );
}

export default async function DashboardPage() {
  const { totalUsers, totalPositions, totalSol, recentUsers } = await getStats();

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-white">Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard label="Total Users" value={totalUsers} />
        <StatCard label="Open Positions" value={totalPositions} sub="across all users" />
        <StatCard
          label="SOL In Play"
          value={`${totalSol.toFixed(2)} SOL`}
          sub="active user balances"
        />
      </div>

      <div className="bg-pulse-card border border-pulse-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 mb-4">Recently Active</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-500 border-b border-pulse-border">
              <th className="text-left pb-2">Username</th>
              <th className="text-left pb-2">Balance</th>
              <th className="text-left pb-2">Status</th>
              <th className="text-left pb-2">Last Active</th>
            </tr>
          </thead>
          <tbody>
            {recentUsers.map((u: any) => (
              <tr key={u.telegram_username} className="border-b border-pulse-border/50">
                <td className="py-2 text-white">@{u.telegram_username}</td>
                <td className="py-2 text-gray-300">{parseFloat(u.sol_balance).toFixed(4)} SOL</td>
                <td className="py-2">
                  <StatusBadge status={u.status} />
                </td>
                <td className="py-2 text-gray-500 text-xs">
                  {new Date(u.last_active_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
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
