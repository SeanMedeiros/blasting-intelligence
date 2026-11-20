import {
  Activity, Bomb, Box, CalendarRange, ClipboardCheck, Cpu, FileBarChart2, FlaskConical, Gauge, LayoutDashboard,
  Database, Settings, ShieldCheck, Target, Users,
} from "lucide-react";

export interface NavItem {
  key: string;
  path: string;
  icon: typeof Gauge;
  n: number;
  /** Shown only to users holding this permission. */
  perm?: string;
}

export const NAV: NavItem[] = [
  { key: "dashboard", path: "/", icon: LayoutDashboard, n: 1 },
  { key: "planning", path: "/planning", icon: CalendarRange, n: 2 },
  { key: "scanning", path: "/scanning", icon: Box, n: 3 },
  { key: "drillholes", path: "/drillholes", icon: Target, n: 4 },
  { key: "blasting", path: "/blasting", icon: Bomb, n: 5 },
  { key: "laboratory", path: "/laboratory", icon: FlaskConical, n: 6 },
  { key: "vibration", path: "/vibration", icon: Activity, n: 7 },
  { key: "detonators", path: "/detonators", icon: Cpu, n: 8 },
  { key: "safety", path: "/safety", icon: ShieldCheck, n: 9 },
  { key: "postblast", path: "/postblast", icon: ClipboardCheck, n: 10 },
  { key: "kpi", path: "/kpi", icon: Gauge, n: 11 },
  { key: "reports", path: "/reports", icon: FileBarChart2, n: 12 },
  { key: "settings", path: "/settings", icon: Settings, n: 13 },
  { key: "masterdata", path: "/masterdata", icon: Database, n: 14 },
  { key: "users", path: "/users", icon: Users, n: 15, perm: "users.manage" },
];
