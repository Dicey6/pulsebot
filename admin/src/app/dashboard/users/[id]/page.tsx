import { supabase } from "@/lib/supabase";
import { notFound } from "next/navigation";
import UserActions from "../UserActions";

async function getData(id: string) {
  const [{ data: user }, { data: positions }, { data: txs }] = await Promise.all([
    supabase.from("users").select("*").eq("id", id).single(),
    supabase
      .from("positions")
      .select("*")
      .eq("user_id", id)
      .order("opened_at", { ascending: false }),
    supabase
      .from("transactions")
      .select("*")
      .eq("user_id", id)
      .order("created_at", { ascending: false })
      .limit(50),
  ]);
  return { user, positions: positions || [], txs: txs || [] };
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-2 border-b border-pulse-border/50 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="text-white text-right max-w-xs break-all">{value}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    active: "bg-green-900/40 text-green-400",
    paused: "bg-yellow-900/40 text-yellow-400",
    restricted: "bg-orange-900/40 text-orange-400",
    banned: "bg-red-900/40 text-red-400",
    open: "bg-blue-900/40 text-blue-400",
    closed: "bg-gray-800 text-gray-500",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[status] ?? "text-gray-400"}`}>
      {status}
    </span>
  );
}

export default async function UserDetailPage({ params }: { params: { id: string } }) {
  const { user, positions, txs } = await getData(params.id);
  if (!user) notFound();

  const addr = user.wallet_address;
  const maskedAddr = `${addr.slice(0, 6)}...${addr.slice(-4)}`;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">@{user.telegram_username}</h1>
        <UserActions userId={user.id} currentStatus={user.status} />
      </div>

      {/* Profile */}
      <div className="bg-pulse-card border border-pulse-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">Profile</h2>
        <Row label="Telegram ID" value={user.telegram_id} />
        <Row label="Status" value={<StatusBadge status={user.status} />} />
        <Row label="SOL Balance" value={`${parseFloat(user.sol_balance).toFixed(4)} SOL`} />
        <Row
          label="Starting Balance"
          value={`${parseFloat(user.starting_balance_sol).toFixed(2)} SOL`}
        />
        <Row label="Wallet Address" value={<span className="font-mono text-xs">{maskedAddr}</span>} />
        <Row label="Joined" value={new Date(user.created_at).toLocaleString()} />
        <Row label="Last Active" value={new Date(user.last_active_at).toLocaleString()} />
      </div>

      {/* Positions */}
      <div className="bg-pulse-card border border-pulse-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">
          Positions ({positions.length})
        </h2>
        {positions.length === 0 ? (
          <p className="text-sm text-gray-600">No positions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 border-b border-pulse-border">
                <th className="text-left pb-2">Token</th>
                <th className="text-left pb-2">Tokens</th>
                <th className="text-left pb-2">Avg Entry</th>
                <th className="text-left pb-2">SOL In</th>
                <th className="text-left pb-2">Status</th>
                <th className="text-left pb-2">Opened</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p: any) => (
                <tr key={p.id} className="border-b border-pulse-border/40">
                  <td className="py-2 text-white font-medium">{p.token_symbol}</td>
                  <td className="py-2 text-gray-300">{parseFloat(p.amount_tokens).toFixed(2)}</td>
                  <td className="py-2 text-gray-300">
                    ${parseFloat(p.avg_entry_price_usd).toFixed(8)}
                  </td>
                  <td className="py-2 text-gray-300">
                    {parseFloat(p.total_sol_invested).toFixed(4)}
                  </td>
                  <td className="py-2">
                    <StatusBadge status={p.status} />
                  </td>
                  <td className="py-2 text-gray-500 text-xs">
                    {new Date(p.opened_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Transaction history */}
      <div className="bg-pulse-card border border-pulse-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-400 mb-3">
          Recent Transactions (last 50)
        </h2>
        {txs.length === 0 ? (
          <p className="text-sm text-gray-600">No transactions.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 border-b border-pulse-border">
                <th className="text-left pb-2">Type</th>
                <th className="text-left pb-2">Token</th>
                <th className="text-left pb-2">SOL</th>
                <th className="text-left pb-2">Price</th>
                <th className="text-left pb-2">Date</th>
              </tr>
            </thead>
            <tbody>
              {txs.map((t: any) => (
                <tr key={t.id} className="border-b border-pulse-border/40">
                  <td className="py-2">
                    <span
                      className={
                        t.type === "buy"
                          ? "text-green-400 font-medium"
                          : "text-red-400 font-medium"
                      }
                    >
                      {t.type.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-2 text-white">{t.token_symbol}</td>
                  <td className="py-2 text-gray-300">{parseFloat(t.sol_amount).toFixed(4)}</td>
                  <td className="py-2 text-gray-300">${parseFloat(t.price_usd).toFixed(8)}</td>
                  <td className="py-2 text-gray-500 text-xs">
                    {new Date(t.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
