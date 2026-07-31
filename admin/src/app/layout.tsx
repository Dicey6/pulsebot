import type { Metadata } from "next";
import "./globals.css";
import { seedAdminIfNeeded } from "@/lib/seed-admin";

export const metadata: Metadata = {
  title: "Pulse Admin",
  description: "Pulse Trading Bot — Admin Dashboard",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  await seedAdminIfNeeded();
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
