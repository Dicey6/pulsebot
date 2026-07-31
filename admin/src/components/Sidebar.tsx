"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "⬛" },
  { href: "/dashboard/users", label: "Users", icon: "👥" },
  { href: "/dashboard/codes", label: "Invite Codes", icon: "🔑" },
  { href: "/dashboard/audit", label: "Audit Log", icon: "📋" },
];

export default function Sidebar() {
  const path = usePathname();

  return (
    <aside className="w-56 min-h-screen bg-pulse-card border-r border-pulse-border flex flex-col">
      {/* Logo */}
      <div className="p-5 border-b border-pulse-border">
        <div className="flex items-center gap-2">
          <span className="w-8 h-8 rounded-full bg-pulse-purple flex items-center justify-center text-white font-bold text-sm">
            P
          </span>
          <span className="font-bold text-white text-sm">Pulse Admin</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1">
        {NAV.map(({ href, label, icon }) => {
          const active =
            href === "/dashboard" ? path === "/dashboard" : path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition ${
                active
                  ? "bg-pulse-purple text-white"
                  : "text-gray-400 hover:text-white hover:bg-pulse-border"
              }`}
            >
              <span>{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Sign out */}
      <div className="p-3 border-t border-pulse-border">
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="w-full text-left text-sm text-gray-500 hover:text-red-400 px-3 py-2 rounded-lg hover:bg-pulse-border transition"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
