// src/helpers.ts
// ============================================================
// دوال مساعدة عامة
// ============================================================
import { InlineKeyboard } from "grammy";
import {
  getUserPerms,
  PERMISSION_NAMES,
  PERMISSIONS_LIST,
} from "./permissions";

/**
 * تهريب HTML لمنع injection
 */
export function cleanText(value: unknown, maxLength = 3500): string {
  if (value === null || value === undefined) return "";
  const str = String(value).trim().slice(0, maxLength);
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * لوحة مفاتيح الإلغاء
 */
export function cancelKb(): InlineKeyboard {
  return new InlineKeyboard().text("❌ إلغاء", "cancel");
}

/**
 * بناء لوحة مفاتيح القائمة الرئيسية بناءً على الصلاحيات
 */
export async function mainMenuKb(userId: number): Promise<InlineKeyboard> {
  const perms = await getUserPerms(userId);
  const kb = new InlineKeyboard();

  const buttons: Array<[string, string, string]> = [
    ["manage_tasks", "📋 المهام", "m_tasks"],
    ["manage_meetings", "📅 الاجتماعات", "m_meets"],
    ["manage_proposals", "💡 المقترحات", "m_props"],
    ["manage_attachments", "📂 الأرشيف", "m_arch"],
    ["view_reports", "📊 التقارير", "m_reps"],
    ["manage_users", "👥 المستخدمين", "m_users"],
  ];

  let count = 0;
  for (const [perm, label, cb] of buttons) {
    if (perms.includes(perm)) {
      if (count > 0 && count % 2 === 0) kb.row();
      kb.text(label, cb);
      count++;
    }
  }
  kb.row().text("👤 ملفي", "m_prof");
  return kb;
}

/**
 * لوحة مفاتيح الصلاحيات
 */
export async function permissionToggleKb(
  userId: number
): Promise<InlineKeyboard> {
  const perms = await getUserPerms(userId);
  const kb = new InlineKeyboard();
  let i = 0;
  for (const p of PERMISSIONS_LIST) {
    const checked = perms.includes(p) ? "✅" : "⬜";
    kb.text(`${checked} ${PERMISSION_NAMES[p]}`, `tog_${p}`);
    i++;
    if (i % 2 === 0) kb.row();
  }
  kb.row()
    .text("💾 اعتماد الصلاحيات", "u_save")
    .row()
    .text("❌ إنهاء", "cancel");
  return kb;
}

export const PERMISSION_NAMES_EXPORT = PERMISSION_NAMES;
