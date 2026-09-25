// src/permissions.ts
// ============================================================
// نظام الصلاحيات
// ============================================================
import {
  getUser,
  getUserPermissions,
  setPermission,
} from "./db";

export const PERMISSIONS_LIST = [
  "manage_tasks",
  "manage_meetings",
  "manage_proposals",
  "manage_attachments",
  "view_reports",
  "manage_users",
];

export const PERMISSION_NAMES: Record<string, string> = {
  manage_tasks: "📋 المهام",
  manage_meetings: "📅 الاجتماعات",
  manage_proposals: "💡 المقترحات",
  manage_attachments: "📂 الأرشيف",
  view_reports: "📊 التقارير",
  manage_users: "👥 المستخدمين",
};

// خريطة بادئات الـ callback → الصلاحية المطلوبة
export const CALLBACK_PREFIX_MAP: Record<string, string> = {
  "t_": "manage_tasks",
  "prio_": "manage_tasks",
  "m_tasks": "manage_tasks",
  "mt_": "manage_meetings",
  "mitem_": "manage_meetings",
  "m_meets": "manage_meetings",
  "p_": "manage_proposals",
  "seldept_": "manage_proposals",
  "d_": "manage_proposals",
  "m_props": "manage_proposals",
  "m_depts": "manage_proposals",
  "att_": "manage_attachments",
  "dl_": "manage_attachments",
  "m_arch": "manage_attachments",
  "exp_": "view_reports",
  "dash": "view_reports",
  "m_reps": "view_reports",
  "u_": "manage_users",
  "tog_": "manage_users",
  "m_users": "manage_users",
};

export async function getUserRole(userId: number): Promise<string> {
  const user = await getUser(userId);
  return user ? user.role : "مستخدم";
}

export async function hasPermission(
  userId: number,
  perm: string
): Promise<boolean> {
  const role = await getUserRole(userId);
  if (role === "مدير نظام") return true;
  const perms = await getUserPermissions(userId);
  return perms.includes(perm);
}

export async function getUserPerms(userId: number): Promise<string[]> {
  const role = await getUserRole(userId);
  if (role === "مدير نظام") return [...PERMISSIONS_LIST];
  return getUserPermissions(userId);
}

export async function setUserPermission(
  userId: number,
  perm: string,
  value: boolean
): Promise<void> {
  await setPermission(userId, perm, value);
}

export function getRequiredPermission(callbackData: string): string | null {
  for (const [prefix, perm] of Object.entries(CALLBACK_PREFIX_MAP)) {
    if (callbackData.startsWith(prefix)) return perm;
  }
  return null;
}
