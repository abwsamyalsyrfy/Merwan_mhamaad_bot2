// src/bot.ts
// ============================================================
// تعريف البوت وإعداد جميع الـ Handlers
// ============================================================
import { Bot, InlineKeyboard, session, Context, SessionFlavor } from "grammy";
import {
  cleanText,
  cancelKb,
  mainMenuKb,
  permissionToggleKb,
} from "./helpers";
import {
  hasPermission,
  getUserPerms,
  setUserPermission,
  getUserRole,
  PERMISSIONS_LIST,
  PERMISSION_NAMES,
} from "./permissions";
import {
  getUser,
  upsertUser,
  getAllUsers,
  deleteUser,
  countUsers,
  getAllDepartments,
  addDepartment,
  deleteDepartment,
  getDepartment,
  countProposalsByDept,
  addTask,
  getTask,
  getTasksByStatus,
  updateTaskStatus,
  deleteTask,
  addTaskUpdate,
  getTaskUpdates,
  countTaskUpdates,
  deleteTaskUpdates,
  getAllTasksForReport,
  getAllTaskUpdatesForReport,
  countTasks,
  countTasksByStatus,
  addMeeting,
  getMeeting,
  getAllMeetings,
  deleteMeeting,
  addMeetingItem,
  getMeetingItems,
  deleteMeetingItems,
  addProposal,
  getProposal,
  getProposalsByDept,
  updateProposalStatus,
  deleteProposal,
  countProposals,
  addProposalUpdate,
  getProposalUpdates,
  deleteProposalUpdates,
  getAllProposalsForReport,
  addAttachment,
  getAttachment,
  getRecentAttachments,
  deleteAttachment,
  deleteAttachmentsByRef,
  countAttachments,
  countMeetings,
} from "./db";
import * as ExcelJS from "exceljs";

// ============================================================
// Session - حالة المحادثة بديل aiogram FSM
// ============================================================
interface SessionData {
  state: string | null;
  taskTitle?: string;
  taskDesc?: string;
  taskPrio?: string;
  meetId?: string;
  meetTitle?: string;
  meetDate?: string;
  deptId?: string;
  propActivity?: string;
  taskIdForUpdate?: string;
  propIdForUpdate?: string;
  refType?: string;
  refId?: string;
  targetUserId?: number;
}

type MyContext = Context & SessionFlavor<SessionData>;

function createBot(token: string): Bot<MyContext> {
  const bot = new Bot<MyContext>(token);

  // إعداد الـ Session
  bot.use(
    session({
      initial: (): SessionData => ({ state: null }),
    })
  );

  // ============================================================
  // Middleware الصلاحيات للـ Callbacks
  // ============================================================
  bot.on("callback_query:data", async (ctx, next) => {
    const data = ctx.callbackQuery.data || "";
    const skipList = [
      "cancel", "m_main", "m_prof", "m_tasks", "m_meets", "m_props",
      "m_arch", "m_reps", "m_users", "m_depts",
    ];
    if (skipList.some((s) => data === s || data.startsWith("m_"))) {
      return next();
    }

    const permMap: Record<string, string> = {
      "t_": "manage_tasks", "prio_": "manage_tasks",
      "mt_": "manage_meetings", "mitem_": "manage_meetings",
      "p_": "manage_proposals", "seldept_": "manage_proposals",
      "d_": "manage_proposals",
      "att_": "manage_attachments", "dl_": "manage_attachments",
      "exp_": "view_reports", "dash": "view_reports",
      "u_": "manage_users", "tog_": "manage_users",
    };

    for (const [prefix, perm] of Object.entries(permMap)) {
      if (data.startsWith(prefix)) {
        const allowed = await hasPermission(ctx.from!.id, perm);
        if (!allowed) {
          await ctx.answerCallbackQuery({
            text: "⛔ لا تملك الصلاحية اللازمة لهذا الإجراء",
            show_alert: true,
          });
          return;
        }
        break;
      }
    }
    return next();
  });

  // ============================================================
  // /start
  // ============================================================
  bot.command("start", async (ctx) => {
    ctx.session.state = null;
    const userId = ctx.from!.id;
    const fullName = ctx.from!.first_name + " " + (ctx.from!.last_name || "");
    const username = ctx.from!.username || "";

    await upsertUser({
      user_id: userId,
      full_name: fullName.trim(),
      username,
      role: "مستخدم",
    });

    const count = await countUsers();
    if (count === 1) {
      await upsertUser({
        user_id: userId,
        full_name: fullName.trim(),
        username,
        role: "مدير نظام",
      });
      for (const p of PERMISSIONS_LIST) {
        await setUserPermission(userId, p, true);
      }
    }

    const kb = await mainMenuKb(userId);
    await ctx.reply(
      `أهلاً بك <b>${cleanText(ctx.from!.first_name)}</b> في نظام متابعة الأداء المتكامل 🚀`,
      { reply_markup: kb, parse_mode: "HTML" }
    );
  });

  // ============================================================
  // /cancel
  // ============================================================
  bot.command("cancel", async (ctx) => {
    ctx.session.state = null;
    const kb = await mainMenuKb(ctx.from!.id);
    await ctx.reply("🏠 تم إلغاء العملية والعودة للرئيسية:", {
      reply_markup: kb,
    });
  });

  // ============================================================
  // إلغاء العملية
  // ============================================================
  bot.callbackQuery("cancel", async (ctx) => {
    ctx.session.state = null;
    const kb = await mainMenuKb(ctx.from!.id);
    await ctx.editMessageText("🏠 القائمة الرئيسية:", { reply_markup: kb });
    await ctx.answerCallbackQuery();
  });

  // ============================================================
  // القائمة الرئيسية - التنقل
  // ============================================================
  bot.callbackQuery("m_main", async (ctx) => {
    const kb = await mainMenuKb(ctx.from!.id);
    await safeEdit(ctx, "🏠 الرئيسية:", kb);
  });

  bot.callbackQuery("m_prof", async (ctx) => {
    const u = await getUser(ctx.from!.id);
    if (!u) {
      await ctx.answerCallbackQuery({ text: "⚠️ السجل غير موجود", show_alert: true });
      return;
    }
    const perms = await getUserPerms(ctx.from!.id);
    const permsTxt =
      perms.map((p) => PERMISSION_NAMES[p] || p).join(", ") || "لا يوجد";
    const txt =
      `👤 <b>${cleanText(u.full_name)}</b>\n` +
      `معرف: <code>${u.user_id}</code>\n` +
      `الدور: ${u.role}\n\n` +
      `الصلاحيات:\n${permsTxt}`;
    const kb = new InlineKeyboard().text("🔙 عودة", "m_main");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery("m_tasks", async (ctx) => {
    const kb = new InlineKeyboard()
      .text("➕ مهمة جديدة", "t_add").row()
      .text("🔍 قيد التنفيذ", "t_list_pend")
      .text("🟢 مكتملة", "t_list_done").row()
      .text("🔙 الرئيسية", "m_main");
    await safeEdit(ctx, "📋 <b>إدارة المهام:</b>", kb);
  });

  bot.callbackQuery("m_meets", async (ctx) => {
    const kb = new InlineKeyboard()
      .text("➕ جدولة اجتماع", "mt_add")
      .text("📋 قائمة الاجتماعات", "mt_list").row()
      .text("🔙 الرئيسية", "m_main");
    await safeEdit(ctx, "📅 <b>إدارة الاجتماعات:</b>", kb);
  });

  bot.callbackQuery("m_props", async (ctx) => {
    const kb = new InlineKeyboard()
      .text("➕ مقترح جديد", "p_add").row()
      .text("📋 عرض حسب الإدارة", "p_list_depts")
      .text("🏢 تنظيم الإدارات", "m_depts").row()
      .text("🔙 الرئيسية", "m_main");
    await safeEdit(ctx, "💡 <b>إدارة المقترحات:</b>", kb);
  });

  bot.callbackQuery("m_depts", async (ctx) => {
    const depts = await getAllDepartments();
    const txt = depts.length
      ? `🏢 <b>الإدارات المسجلة:</b>\n\n${depts.map((d) => `▪️ ${cleanText(d.name)}`).join("\n")}`
      : "🏢 لا يوجد إدارات حالياً.";
    const kb = new InlineKeyboard().text("➕ إضافة إدارة", "d_add").row();
    for (const d of depts) {
      kb.text(`🗑 حذف: ${d.name.slice(0, 22)}`, `d_delete_${d.id}`).row();
    }
    kb.text("🔙 عودة", "m_props");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery("m_arch", async (ctx) => {
    const atts = await getRecentAttachments();
    if (!atts.length) {
      const kb = new InlineKeyboard().text("🔙 الرئيسية", "m_main");
      await safeEdit(ctx, "📂 الأرشيف المركزي فارغ.", kb);
      return;
    }
    let txt = "📂 <b>أحدث الملفات المؤرشفة:</b>\n\n";
    const kb = new InlineKeyboard();
    for (const a of atts) {
      txt += `📎 ${cleanText(a.file_name)}\nنوع الارتباط: ${a.ref_type} #${a.ref_id} | 📅 ${a.uploaded_at.slice(0, 16)}\n\n`;
      kb.text(`📥 ${a.file_name.slice(0, 15)}...`, `dl_${a.id}`)
        .text(`🗑 حذف #${a.id}`, `att_delete_${a.id}`).row();
    }
    kb.text("🔙 الرئيسية", "m_main");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery("m_reps", async (ctx) => {
    const kb = new InlineKeyboard()
      .text("📊 تقرير المهام", "exp_tasks")
      .text("📊 تقرير المقترحات", "exp_props").row()
      .text("📊 تقرير المتابعات", "exp_updates")
      .text("📈 لوحة المؤشرات", "dash").row()
      .text("🔙 الرئيسية", "m_main");
    await safeEdit(ctx, "📊 <b>مركز التقارير والإحصائيات:</b>", kb);
  });

  bot.callbackQuery("m_users", async (ctx) => {
    const users = await getAllUsers();
    const kb = new InlineKeyboard().text("➕ تسجيل مستخدم جديد", "u_add").row();
    for (const u of users) {
      const icon = u.role === "مدير نظام" ? "👑" : "👤";
      kb.text(`${icon} ${u.full_name}`, `u_view_${u.user_id}`).row();
    }
    kb.text("🔙 الرئيسية", "m_main");
    await safeEdit(ctx, "👥 <b>إدارة هيكل المستخدمين:</b>", kb);
  });

  // ============================================================
  // المهام - Tasks
  // ============================================================
  bot.callbackQuery("t_add", async (ctx) => {
    ctx.session.state = "task_title";
    await safeEdit(ctx, "✏️ <b>أدخل عنوان المهمة الجديدة:</b>", cancelKb());
  });

  bot.callbackQuery(/^t_list_(.+)$/, async (ctx) => {
    const status = ctx.match[1] === "pend" ? "قيد التنفيذ" : "مكتملة";
    const tasks = await getTasksByStatus(status);
    if (!tasks.length) {
      const kb = new InlineKeyboard().text("🔙 عودة", "m_tasks");
      await safeEdit(ctx, `📭 سجل المهام فارغ للحالة: ${status}.`, kb);
      return;
    }
    const kb = new InlineKeyboard();
    for (const t of tasks) {
      const icon = t.priority === "عالية" ? "🔴" : t.priority === "متوسطة" ? "🟡" : "🟢";
      kb.text(`${icon} #${t.id.slice(-4)} | ${t.title.slice(0, 25)}`, `t_view_${t.id}`).row();
    }
    kb.text("🔙 عودة للمهام", "m_tasks");
    await safeEdit(ctx, `📋 <b>استعراض المهام (${status}):</b>`, kb);
  });

  bot.callbackQuery(/^t_view_(.+)$/, async (ctx) => {
    const tid = ctx.match[1];
    const t = await getTask(tid);
    if (!t) {
      await ctx.answerCallbackQuery({ text: "⚠️ السجل غير موجود", show_alert: true });
      return;
    }
    const updCount = await countTaskUpdates(tid);
    const txt =
      `📌 <b>المهمة #${t.id.slice(-4)}: ${cleanText(t.title)}</b>\n` +
      `──────────────\n` +
      `📝 الوصف: ${cleanText(t.description)}\n` +
      `🎯 الأولوية: ${t.priority}\n` +
      `📅 الاستحقاق: ${cleanText(t.due_date)}\n` +
      `🔄 الحالة: ${t.status}\n` +
      `💬 الإفادات: ${updCount}\n`;

    const kb = new InlineKeyboard();
    if (t.status !== "مكتملة") {
      kb.text("✅ إغلاق واعتماد الإكمال", `t_done_${tid}`).row()
        .text("💬 رفع إفادة/متابعة", `t_add_upd_${tid}`)
        .text("📜 عرض سجل الإفادات", `t_upds_${tid}`).row()
        .text("📎 إرفاق مستند", `att_start_task_${tid}`)
        .text("🗑 حذف المهمة", `t_delete_${tid}`).row()
        .text("🔙 القائمة", "m_tasks");
    } else {
      kb.text("📜 عرض سجل الإفادات", `t_upds_${tid}`)
        .text("📎 إرفاق مستند", `att_start_task_${tid}`).row()
        .text("🗑 حذف المهمة", `t_delete_${tid}`)
        .text("🔙 القائمة", "m_tasks");
    }
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^t_done_(.+)$/, async (ctx) => {
    const tid = ctx.match[1];
    await updateTaskStatus(tid, "مكتملة");
    await ctx.answerCallbackQuery({ text: "✅ تم اعتماد إكمال المهمة" });
    // إعادة عرض المهمة
    ctx.callbackQuery.data = `t_view_${tid}`;
    ctx.match = /^t_view_(.+)$/.exec(`t_view_${tid}`)!;
    const t = await getTask(tid);
    if (!t) return;
    const updCount = await countTaskUpdates(tid);
    const txt =
      `📌 <b>المهمة #${t.id.slice(-4)}: ${cleanText(t.title)}</b>\n──────────────\n` +
      `🔄 الحالة: ${t.status}\n💬 الإفادات: ${updCount}`;
    const kb = new InlineKeyboard()
      .text("📜 عرض سجل الإفادات", `t_upds_${tid}`)
      .text("🗑 حذف", `t_delete_${tid}`).row()
      .text("🔙 القائمة", "m_tasks");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^t_delete_confirm_(.+)$/, async (ctx) => {
    const tid = ctx.match[1];
    await deleteTaskUpdates(tid);
    await deleteAttachmentsByRef("task", tid);
    await deleteTask(tid);
    await ctx.answerCallbackQuery({ text: "✅ تم حذف المهمة نهائياً" });
    const kb = new InlineKeyboard().text("🔙 قائمة المهام", "m_tasks");
    await safeEdit(ctx, "✅ تم حذف المهمة.", kb);
  });

  bot.callbackQuery(/^t_delete_(.+)$/, async (ctx) => {
    const tid = ctx.match[1];
    if (tid.startsWith("confirm_")) return; // معالجة بـ handler آخر
    const t = await getTask(tid);
    if (!t) {
      await ctx.answerCallbackQuery({ text: "⚠️ المهمة غير موجودة", show_alert: true });
      return;
    }
    const kb = new InlineKeyboard()
      .text("✅ نعم، احذف نهائياً", `t_delete_confirm_${tid}`).row()
      .text("❌ إلغاء", `t_view_${tid}`);
    await safeEdit(
      ctx,
      `⚠️ <b>تأكيد حذف المهمة</b>\n\n${cleanText(t.title)}\n\nسيتم حذف المتابعات والمرفقات.`,
      kb
    );
  });

  bot.callbackQuery(/^t_add_upd_(.+)$/, async (ctx) => {
    const tid = ctx.match[1];
    ctx.session.state = "task_update";
    ctx.session.taskIdForUpdate = tid;
    await safeEdit(ctx, "💬 <b>الرجاء كتابة نص الإفادة لتوثيق المتابعة:</b>", cancelKb());
  });

  bot.callbackQuery(/^t_upds_(.+)$/, async (ctx) => {
    const tid = ctx.match[1];
    const updates = await getTaskUpdates(tid);
    let txt = `📜 <b>سجل متابعة المهمة #${tid.slice(-4)}:</b>\n\n`;
    if (!updates.length) {
      txt += "لم يتم تسجيل أي إفادات بعد.";
    } else {
      for (let i = 0; i < updates.length; i++) {
        const u = updates[i];
        const user = await getUser(u.created_by);
        const name = cleanText(user?.full_name || "مستخدم غير معروف");
        txt += `<b>${i + 1}. ${name}</b> <i>(${u.created_at.slice(0, 16)})</i>:\n🔹 ${cleanText(u.update_text)}\n\n`;
      }
    }
    const kb = new InlineKeyboard().text("🔙 عودة للمهمة", `t_view_${tid}`);
    await safeEdit(ctx, txt, kb);
  });

  // ============================================================
  // الاجتماعات - Meetings
  // ============================================================
  bot.callbackQuery("mt_add", async (ctx) => {
    ctx.session.state = "meet_title";
    await safeEdit(ctx, "✏️ <b>أدخل موضوع/عنوان الاجتماع:</b>", cancelKb());
  });

  bot.callbackQuery("mt_list", async (ctx) => {
    const meets = await getAllMeetings();
    if (!meets.length) {
      const kb = new InlineKeyboard().text("🔙 عودة", "m_meets");
      await safeEdit(ctx, "📭 لا توجد اجتماعات مجدولة.", kb);
      return;
    }
    const kb = new InlineKeyboard();
    for (const m of meets) {
      kb.text(`📅 ${m.title.slice(0, 20)} | ${m.meeting_date}`, `mt_view_${m.id}`).row();
    }
    kb.text("🔙 عودة للاجتماعات", "m_meets");
    await safeEdit(ctx, "📋 <b>أجندة الاجتماعات:</b>", kb);
  });

  bot.callbackQuery(/^mt_view_(.+)$/, async (ctx) => {
    const mid = ctx.match[1];
    const m = await getMeeting(mid);
    if (!m) {
      await ctx.answerCallbackQuery({ text: "⚠️ غير موجود", show_alert: true });
      return;
    }
    const items = await getMeetingItems(mid);
    let txt =
      `📅 <b>عنوان الاجتماع:</b> ${cleanText(m.title)}\n` +
      `📆 <b>التاريخ:</b> ${cleanText(m.meeting_date)}\n` +
      `📍 <b>المقر:</b> ${cleanText(m.location)}\n` +
      `──────────────\n` +
      `📌 <b>جدول الأعمال والمقررات:</b>\n`;
    if (!items.length) {
      txt += "<i>لم يتم إدراج بنود بعد.</i>";
    } else {
      items.forEach((item, i) => {
        const icon = item.item_type === "مقرر" ? "⚖️" : "📝";
        txt += `<b>${i + 1}.</b> ${icon} [${item.item_type}] ${cleanText(item.item_text)}\n`;
      });
    }
    const kb = new InlineKeyboard()
      .text("➕ إدراج بند/مقرر", `mt_add_item_${mid}`)
      .text("📎 إرفاق محضر", `att_start_meet_${mid}`).row()
      .text("🗑 حذف الاجتماع", `mt_delete_${mid}`)
      .text("🔙 القائمة", "m_meets");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^mt_add_item_(.+)$/, async (ctx) => {
    const mid = ctx.match[1];
    ctx.session.meetId = mid;
    const kb = new InlineKeyboard()
      .text("📝 بند أعمال (للنقاش)", `mitem_بند`).row()
      .text("⚖️ مقرر (قرار معتمد)", `mitem_مقرر`);
    await safeEdit(ctx, "<b>حدد تصنيف الإدراج المطلوب:</b>", kb);
  });

  bot.callbackQuery(/^mitem_(.+)$/, async (ctx) => {
    const itype = ctx.match[1];
    ctx.session.state = "meet_item_text";
    ctx.session.taskTitle = itype; // نستخدم taskTitle لحفظ نوع البند مؤقتاً
    await safeEdit(ctx, `✏️ <b>أدخل الصياغة النهائية للـ ${itype}:</b>`, cancelKb());
  });

  bot.callbackQuery(/^mt_delete_confirm_(.+)$/, async (ctx) => {
    const mid = ctx.match[1];
    await deleteMeetingItems(mid);
    await deleteAttachmentsByRef("meet", mid);
    await deleteMeeting(mid);
    await ctx.answerCallbackQuery({ text: "✅ تم حذف الاجتماع نهائياً" });
    const kb = new InlineKeyboard().text("🔙 قائمة الاجتماعات", "m_meets");
    await safeEdit(ctx, "✅ تم حذف الاجتماع.", kb);
  });

  bot.callbackQuery(/^mt_delete_(.+)$/, async (ctx) => {
    const mid = ctx.match[1];
    if (mid.startsWith("confirm_")) return;
    const m = await getMeeting(mid);
    if (!m) {
      await ctx.answerCallbackQuery({ text: "⚠️ الاجتماع غير موجود", show_alert: true });
      return;
    }
    const kb = new InlineKeyboard()
      .text("✅ نعم، احذف نهائياً", `mt_delete_confirm_${mid}`).row()
      .text("❌ إلغاء", `mt_view_${mid}`);
    await safeEdit(
      ctx,
      `⚠️ <b>تأكيد حذف الاجتماع #${mid.slice(-4)}</b>\n\n${cleanText(m.title)}\n\nسيتم حذف البنود والمرفقات.`,
      kb
    );
  });

  // ============================================================
  // المقترحات - Proposals
  // ============================================================
  bot.callbackQuery("p_add", async (ctx) => {
    const depts = await getAllDepartments();
    if (!depts.length) {
      await ctx.answerCallbackQuery({ text: "⚠️ يرجى تأسيس الإدارات أولاً.", show_alert: true });
      return;
    }
    const kb = new InlineKeyboard();
    let i = 0;
    for (const d of depts) {
      kb.text(`🏢 ${d.name}`, `seldept_${d.id}`);
      i++;
      if (i % 2 === 0) kb.row();
    }
    kb.row().text("❌ إلغاء", "cancel");
    await safeEdit(ctx, "🎯 <b>حدد الإدارة المعنية بالمقترح:</b>", kb);
  });

  bot.callbackQuery(/^seldept_(.+)$/, async (ctx) => {
    const deptId = ctx.match[1];
    ctx.session.deptId = deptId;
    ctx.session.state = "prop_activity";
    await safeEdit(ctx, "✏️ <b>اكتب وصف النشاط أو المقترح التطويري:</b>", cancelKb());
  });

  bot.callbackQuery("p_list_depts", async (ctx) => {
    const depts = await getAllDepartments();
    if (!depts.length) {
      const kb = new InlineKeyboard().text("🔙 عودة", "m_props");
      await safeEdit(ctx, "📭 لا يوجد هيكل إداري مسجل.", kb);
      return;
    }
    const kb = new InlineKeyboard();
    for (const d of depts) {
      const cnt = await countProposalsByDept(d.id);
      kb.text(`${d.name} (مقترحات: ${cnt})`, `p_list_${d.id}`).row();
    }
    kb.text("🔙 عودة", "m_props");
    await safeEdit(ctx, "📋 <b>حدد الإدارة لاستعراض مقترحاتها:</b>", kb);
  });

  bot.callbackQuery(/^p_list_(.+)$/, async (ctx) => {
    const deptId = ctx.match[1];
    const props = await getProposalsByDept(deptId);
    if (!props.length) {
      const kb = new InlineKeyboard().text("🔙 عودة للإدارات", "p_list_depts");
      await safeEdit(ctx, "📭 لا توجد مقترحات مسجلة لهذه الإدارة.", kb);
      return;
    }
    const kb = new InlineKeyboard();
    for (const p of props) {
      const icon = p.status === "مقترح" ? "🟡" : p.status === "مكتمل" ? "🟢" : "🔵";
      kb.text(`${icon} ${p.activity.slice(0, 30)}...`, `p_view_${p.id}`).row();
    }
    kb.text("🔙 تنظيم الإدارات", "p_list_depts");
    await safeEdit(ctx, "📋 <b>بنك المقترحات للإدارة المحددة:</b>", kb);
  });

  bot.callbackQuery(/^p_view_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    const p = await getProposal(pid);
    if (!p) {
      await ctx.answerCallbackQuery({ text: "⚠️ السجل مفقود", show_alert: true });
      return;
    }
    const dept = await getDepartment(p.dept_id);
    const deptName = dept ? dept.name : "غير محدد";
    const updCount = await (async () => {
      const upds = await getProposalUpdates(pid);
      return upds.length;
    })();

    const txt =
      `💡 <b>بطاقة مقترح #${pid.slice(-4)}</b>\n──────────────\n` +
      `🏢 الإدارة: ${cleanText(deptName)}\n` +
      `📝 النشاط:\n${cleanText(p.activity)}\n` +
      `⏱ التقدير الزمني: ${cleanText(p.proposed_time)}\n` +
      `📌 الحالة: ${p.status}\n` +
      `💬 إجراءات المتابعة: ${updCount}\n\n` +
      `🔽 <b>التوجيه الإداري للمقترح:</b>`;

    const kb = new InlineKeyboard();
    if (p.status === "مقترح") {
      kb.text("✅ تحويل لمهام تنفيذية", `p_conv_task_${pid}`).row()
        .text("📅 إدراج بجدول اجتماع", `p_conv_meet_${pid}`).row()
        .text("✔️ اعتماد الإغلاق", `p_done_${pid}`).row();
    } else {
      kb.text("🔄 إعادة التنشيط", `p_reopen_${pid}`).row();
    }
    kb.text("💬 رفع إفادة", `p_add_upd_${pid}`)
      .text("📜 السجل التاريخي", `p_upds_${pid}`).row()
      .text("🗑 حذف المقترح", `p_delete_${pid}`).row()
      .text("🔙 القائمة", "p_list_depts");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^p_conv_task_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    const p = await getProposal(pid);
    if (!p) { await ctx.answerCallbackQuery({ text: "⚠️ خطأ" }); return; }
    const taskId = await addTask({
      title: `تنفيذ مقترح: ${p.activity.slice(0, 20)}`,
      description: `مُحال من مقترح #${pid}:\n${p.activity}`,
      priority: "متوسطة",
      due_date: p.proposed_time,
      created_by: ctx.from!.id,
    });
    await updateProposalStatus(pid, "قيد التنفيذ", { converted_to_task: taskId });
    await ctx.answerCallbackQuery({ text: "✅ تمت إحالة المقترح إلى مسار المهام" });
    // إعادة عرض المقترح
    ctx.callbackQuery.data = `p_view_${pid}`;
  });

  bot.callbackQuery(/^p_conv_meet_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    const p = await getProposal(pid);
    if (!p) { await ctx.answerCallbackQuery({ text: "⚠️ خطأ" }); return; }
    const meetId = await addMeeting({
      title: `جلسة مراجعة مقترح #${pid.slice(-4)}`,
      meeting_date: p.proposed_time,
      location: "يحدد لاحقاً",
      created_by: ctx.from!.id,
    });
    await addMeetingItem(meetId, "بند", `استعراض ودراسة الجدوى:\n${p.activity}`);
    await updateProposalStatus(pid, "قيد التنفيذ", { converted_to_meeting: meetId });
    await ctx.answerCallbackQuery({ text: "✅ تم تشكيل أجندة اجتماع خاصة بالمقترح" });
  });

  bot.callbackQuery(/^p_done_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    await updateProposalStatus(pid, "مكتمل");
    await ctx.answerCallbackQuery({ text: "✅ تم تحديث دورة الاعتماد للإنهاء" });
  });

  bot.callbackQuery(/^p_reopen_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    await updateProposalStatus(pid, "مقترح");
    await ctx.answerCallbackQuery({ text: "🔄 تم إعادة تنشيط السجل" });
  });

  bot.callbackQuery(/^p_add_upd_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    ctx.session.state = "prop_update";
    ctx.session.propIdForUpdate = pid;
    await safeEdit(ctx, "💬 <b>أدخل إفادة الدعم والمتابعة للمقترح:</b>", cancelKb());
  });

  bot.callbackQuery(/^p_upds_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    const updates = await getProposalUpdates(pid);
    let txt = `📜 <b>السجل التوثيقي للمقترح #${pid.slice(-4)}:</b>\n\n`;
    if (!updates.length) {
      txt += "السجل فارغ من التدخلات.";
    } else {
      for (let i = 0; i < updates.length; i++) {
        const u = updates[i];
        const user = await getUser(u.created_by);
        const name = cleanText(user?.full_name || "مستخدم النظام");
        txt += `<b>${i + 1}. ${name}</b> <i>(${u.created_at.slice(0, 16)})</i>:\n🔹 ${cleanText(u.update_text)}\n\n`;
      }
    }
    const kb = new InlineKeyboard().text("🔙 رجوع", `p_view_${pid}`);
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^p_delete_confirm_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    await deleteProposalUpdates(pid);
    await deleteProposal(pid);
    await ctx.answerCallbackQuery({ text: "✅ تم حذف المقترح نهائياً" });
    const kb = new InlineKeyboard().text("🔙 عودة", "p_list_depts");
    await safeEdit(ctx, "✅ تم حذف المقترح.", kb);
  });

  bot.callbackQuery(/^p_delete_(.+)$/, async (ctx) => {
    const pid = ctx.match[1];
    if (pid.startsWith("confirm_")) return;
    const p = await getProposal(pid);
    if (!p) {
      await ctx.answerCallbackQuery({ text: "⚠️ المقترح غير موجود", show_alert: true });
      return;
    }
    const kb = new InlineKeyboard()
      .text("✅ نعم، احذف نهائياً", `p_delete_confirm_${pid}`).row()
      .text("❌ إلغاء", `p_view_${pid}`);
    await safeEdit(
      ctx,
      `⚠️ <b>تأكيد حذف المقترح</b>\n\n${cleanText(p.activity)}\n\nسيتم حذف سجل المتابعات.`,
      kb
    );
  });

  // ============================================================
  // الإدارات - Departments
  // ============================================================
  bot.callbackQuery("d_add", async (ctx) => {
    ctx.session.state = "dept_name";
    await safeEdit(ctx, "✏️ <b>أدخل المسمى الرسمي للإدارة:</b>", cancelKb());
  });

  bot.callbackQuery(/^d_delete_confirm_(.+)$/, async (ctx) => {
    const did = ctx.match[1];
    await deleteDepartment(did);
    await ctx.answerCallbackQuery({ text: "✅ تم حذف الإدارة" });
    // إعادة عرض قائمة الإدارات
    ctx.callbackQuery.data = "m_depts";
  });

  bot.callbackQuery(/^d_delete_(.+)$/, async (ctx) => {
    const did = ctx.match[1];
    if (did.startsWith("confirm_")) return;
    const dept = await getDepartment(did);
    if (!dept) {
      await ctx.answerCallbackQuery({ text: "⚠️ الإدارة غير موجودة", show_alert: true });
      return;
    }
    const cnt = await countProposalsByDept(did);
    if (cnt > 0) {
      await ctx.answerCallbackQuery({ text: "⛔ احذف مقترحات الإدارة أولاً", show_alert: true });
      return;
    }
    const kb = new InlineKeyboard()
      .text("✅ نعم، احذف الإدارة", `d_delete_confirm_${did}`).row()
      .text("❌ إلغاء", "m_depts");
    await safeEdit(ctx, `⚠️ <b>تأكيد حذف الإدارة</b>\n\n${cleanText(dept.name)}`, kb);
  });

  // ============================================================
  // الأرشيف - Attachments
  // ============================================================
  bot.callbackQuery(/^att_start_(.+)_(.+)$/, async (ctx) => {
    const refType = ctx.match[1];
    const refId = ctx.match[2];
    ctx.session.state = "attach_file";
    ctx.session.refType = refType;
    ctx.session.refId = refId;
    await safeEdit(ctx, "📎 <b>الرجاء توجيه أو رفع المستند (PDF أو صور):</b>", cancelKb());
  });

  bot.callbackQuery(/^dl_(.+)$/, async (ctx) => {
    const attId = ctx.match[1];
    const att = await getAttachment(attId);
    if (!att) {
      await ctx.answerCallbackQuery({ text: "⚠️ المستند مفقود", show_alert: true });
      return;
    }
    try {
      if (att.file_type === "photo") {
        await ctx.replyWithPhoto(att.file_id, { caption: `🖼 صورة مرفقة: ${att.file_name}` });
      } else {
        await ctx.replyWithDocument(att.file_id, { caption: `📥 مستخرج: ${att.file_name}` });
      }
      await ctx.answerCallbackQuery({ text: "تم الاستخراج بنجاح" });
    } catch {
      await ctx.answerCallbackQuery({ text: "⚠️ تعذر استخراج الملف", show_alert: true });
    }
  });

  bot.callbackQuery(/^att_delete_confirm_(.+)$/, async (ctx) => {
    const aid = ctx.match[1];
    await deleteAttachment(aid);
    await ctx.answerCallbackQuery({ text: "✅ تم حذف المرفق" });
    const kb = new InlineKeyboard().text("🔙 الأرشيف", "m_arch");
    await safeEdit(ctx, "✅ تم حذف المرفق.", kb);
  });

  bot.callbackQuery(/^att_delete_(.+)$/, async (ctx) => {
    const aid = ctx.match[1];
    if (aid.startsWith("confirm_")) return;
    const att = await getAttachment(aid);
    if (!att) {
      await ctx.answerCallbackQuery({ text: "⚠️ المرفق غير موجود", show_alert: true });
      return;
    }
    const kb = new InlineKeyboard()
      .text("✅ نعم، احذف المرفق", `att_delete_confirm_${aid}`).row()
      .text("❌ إلغاء", "m_arch");
    await safeEdit(ctx, `⚠️ <b>تأكيد حذف المرفق</b>\n\n${cleanText(att.file_name)}`, kb);
  });

  // ============================================================
  // التقارير - Reports
  // ============================================================
  bot.callbackQuery(/^exp_(.+)$/, async (ctx) => {
    await ctx.answerCallbackQuery({ text: "⏳ جاري سحب ومعالجة البيانات..." });
    const expType = ctx.match[1];
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet("المستخرج الآلي");
    let filename = "System_Report";

    if (expType === "tasks") {
      filename = `سجل_المهام_التنفيذية_${new Date().toISOString().slice(0, 10)}.xlsx`;
      worksheet.columns = [
        { header: "الرقم المرجعي", key: "id", width: 20 },
        { header: "عنوان المهمة", key: "title", width: 30 },
        { header: "التفاصيل", key: "description", width: 40 },
        { header: "مستوى الأولوية", key: "priority", width: 15 },
        { header: "الحالة الراهنة", key: "status", width: 15 },
        { header: "موعد الاستحقاق", key: "due_date", width: 20 },
        { header: "تاريخ التأسيس", key: "created_at", width: 20 },
      ];
      const tasks = await getAllTasksForReport();
      tasks.forEach((t) => worksheet.addRow(t));
    } else if (expType === "props") {
      filename = `حصاد_المقترحات_التطويرية_${new Date().toISOString().slice(0, 10)}.xlsx`;
      worksheet.columns = [
        { header: "الرقم", key: "id", width: 20 },
        { header: "الإدارة المستفيدة", key: "dept_name", width: 25 },
        { header: "التدخل المقترح", key: "activity", width: 40 },
        { header: "الإطار الزمني", key: "proposed_time", width: 20 },
        { header: "دورة الاعتماد", key: "status", width: 15 },
      ];
      const props = await getAllProposalsForReport();
      for (const p of props) {
        const dept = await getDepartment(p.dept_id);
        worksheet.addRow({ ...p, dept_name: dept?.name || "غير محدد" });
      }
    } else if (expType === "updates") {
      filename = `مؤشرات_المتابعة_والإفادات_${new Date().toISOString().slice(0, 10)}.xlsx`;
      worksheet.columns = [
        { header: "رقم الربط (مهمة)", key: "task_id", width: 20 },
        { header: "عنوان المهمة", key: "task_title", width: 30 },
        { header: "نص الإفادة", key: "update_text", width: 40 },
        { header: "تاريخ الحركة", key: "created_at", width: 20 },
        { header: "القائم بالتحديث", key: "updated_by", width: 25 },
      ];
      const updates = await getAllTaskUpdatesForReport();
      for (const u of updates) {
        const task = await getTask(u.task_id);
        const user = await getUser(u.created_by);
        worksheet.addRow({
          ...u,
          task_title: task?.title || "غير محدد",
          updated_by: user?.full_name || "غير معروف",
        });
      }
    }

    const buffer = await workbook.xlsx.writeBuffer();
    await ctx.replyWithDocument(
      { source: Buffer.from(buffer), filename },
      {
        caption:
          "📊 <b>تم إصدار التقرير بنجاح.</b>\nيمكنك استخدام البيانات في تحليلات Excel أو PowerBI.",
        parse_mode: "HTML",
      }
    );
  });

  bot.callbackQuery("dash", async (ctx) => {
    const tCnt = await countTasks();
    const tDone = await countTasksByStatus("مكتملة");
    const pCnt = await countProposals();
    const mCnt = await countMeetings();
    const aCnt = await countAttachments();
    const compRate = tCnt > 0 ? Math.round((tDone / tCnt) * 100 * 10) / 10 : 0;

    const txt =
      `📈 <b>لوحة المؤشرات التشغيلية للنظام:</b>\n\n` +
      `✅ <b>المهام الكلية:</b> ${tCnt} (المنجز: ${tDone})\n` +
      `🎯 <b>معدل الإنجاز العام:</b> ${compRate}%\n` +
      `──────────────\n` +
      `💡 <b>بنك المقترحات:</b> ${pCnt} نشاط مسجل\n` +
      `📅 <b>لجان واجتماعات:</b> ${mCnt} محضر\n` +
      `📂 <b>وثائق الأرشيف:</b> ${aCnt} مستند مرفق`;

    const kb = new InlineKeyboard().text("🔙 عودة للتقارير", "m_reps");
    await safeEdit(ctx, txt, kb);
  });

  // ============================================================
  // إدارة المستخدمين - Users
  // ============================================================
  bot.callbackQuery("u_add", async (ctx) => {
    ctx.session.state = "user_add_id";
    await safeEdit(ctx, "✏️ <b>أدخل المعرف الرقمي (Telegram ID) للموظف:</b>", cancelKb());
  });

  bot.callbackQuery(/^u_view_(\d+)$/, async (ctx) => {
    const uid = parseInt(ctx.match[1]);
    const u = await getUser(uid);
    if (!u) {
      await ctx.answerCallbackQuery({ text: "⚠️ السجل الوظيفي مفقود", show_alert: true });
      return;
    }
    const perms = await getUserPerms(uid);
    const permsTxt = perms.map((p) => `▪️ ${PERMISSION_NAMES[p] || p}`).join("\n") || "بدون صلاحيات إدارية";
    const txt =
      `👤 <b>بطاقة الموظف:</b> ${cleanText(u.full_name)} (@${cleanText(u.username)})\n` +
      `المستوى: ${u.role}\n──────────────\n` +
      `<b>محددات الوصول والنطاق:</b>\n${permsTxt}`;

    const kb = new InlineKeyboard();
    if (uid !== ctx.from!.id) {
      kb.text("🔧 تعديل الصلاحيات", `u_edit_${uid}`).row();
      if (u.role === "مستخدم") {
        kb.text("👑 ترقية لمدير نظام", `u_mk_admin_${uid}`).row();
      } else {
        kb.text("👤 سحب الصلاحية العليا", `u_mk_user_${uid}`).row();
      }
      kb.text("🗑 طي القيد (حذف)", `u_del_${uid}`).row();
    }
    kb.text("🔙 القائمة", "m_users");
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^u_edit_(\d+)$/, async (ctx) => {
    const uid = parseInt(ctx.match[1]);
    ctx.session.state = "user_perm_set";
    ctx.session.targetUserId = uid;
    const kb = await permissionToggleKb(uid);
    const txt = `🔧 <b>لوحة التحكم في الصلاحيات</b> (رقم المستخدم: <code>${uid}</code>):`;
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery(/^tog_(.+)$/, async (ctx) => {
    const perm = ctx.match[1];
    if (!ctx.session.targetUserId) return;
    const uid = ctx.session.targetUserId;
    const current = await hasPermission(uid, perm);
    await setUserPermission(uid, perm, !current);
    const kb = await permissionToggleKb(uid);
    const txt = `🔧 <b>لوحة التحكم في الصلاحيات</b> (رقم المستخدم: <code>${uid}</code>):`;
    await safeEdit(ctx, txt, kb);
  });

  bot.callbackQuery("u_save", async (ctx) => {
    const uid = ctx.session.targetUserId;
    if (!uid) return;
    if (!(await getUser(uid))) {
      await upsertUser({
        user_id: uid,
        full_name: `موظف_${uid}`,
        username: `u${uid}`,
        role: "مستخدم",
      });
    }
    ctx.session.state = null;
    ctx.session.targetUserId = undefined;
    const kb = new InlineKeyboard().text("🔙 عودة للهيكل التنظيمي", "m_users");
    await safeEdit(
      ctx,
      `✅ تم تفعيل حساب الموظف برقم (<code>${uid}</code>) بنجاح وإدراجه بالهيكل.`,
      kb
    );
  });

  bot.callbackQuery(/^u_mk_admin_(\d+)$/, async (ctx) => {
    const uid = parseInt(ctx.match[1]);
    const u = await getUser(uid);
    if (u) await upsertUser({ ...u, role: "مدير نظام" });
    for (const p of PERMISSIONS_LIST) {
      await setUserPermission(uid, p, true);
    }
    await ctx.answerCallbackQuery({ text: "✅ تمت الترقية التشغيلية بنجاح" });
  });

  bot.callbackQuery(/^u_mk_user_(\d+)$/, async (ctx) => {
    const uid = parseInt(ctx.match[1]);
    const u = await getUser(uid);
    if (u) await upsertUser({ ...u, role: "مستخدم" });
    await ctx.answerCallbackQuery({ text: "✅ تم إعادة تعيين المستوى الإداري" });
  });

  bot.callbackQuery(/^u_del_exec_(\d+)$/, async (ctx) => {
    const uid = parseInt(ctx.match[1]);
    await deleteUser(uid);
    await deleteAllPermissions(uid);
    await ctx.answerCallbackQuery({ text: "✅ تم تطبيق طي القيد وإلغاء الوصول" });
    const kb = new InlineKeyboard().text("🔙 قائمة المستخدمين", "m_users");
    await safeEdit(ctx, "✅ تم حذف المستخدم.", kb);
  });

  // يجب تحديد هذا الـ handler بعد u_del_exec
  bot.callbackQuery(/^u_del_(\d+)$/, async (ctx) => {
    const uid = parseInt(ctx.match[1]);
    const kb = new InlineKeyboard()
      .text("✅ تأكيد الإجراء", `u_del_exec_${uid}`)
      .text("❌ تراجع", `u_view_${uid}`);
    await safeEdit(
      ctx,
      "⚠️ هل أنت متأكد من قرار طي قيد هذا المستخدم وإلغاء ارتباطه بالنظام؟",
      kb
    );
  });

  // ============================================================
  // معالجة الرسائل النصية (FSM بديل aiogram)
  // ============================================================
  bot.on("message:text", async (ctx) => {
    const state = ctx.session.state;
    const text = ctx.message.text.trim();

    // --------- إضافة مهمة ---------
    if (state === "task_title") {
      if (text.length < 3) {
        await ctx.reply("⚠️ العنوان قصير جداً. حاول مرة أخرى:", { reply_markup: cancelKb() });
        return;
      }
      ctx.session.taskTitle = text;
      ctx.session.state = "task_desc";
      await ctx.reply("📝 <b>أدخل تفاصيل ووصف المهمة:</b>", {
        reply_markup: cancelKb(),
        parse_mode: "HTML",
      });
      return;
    }

    if (state === "task_desc") {
      ctx.session.taskDesc = text;
      ctx.session.state = "task_prio";
      const kb = new InlineKeyboard()
        .text("🔴 أولوية عالية", "prio_عالية").row()
        .text("🟡 أولوية متوسطة", "prio_متوسطة").row()
        .text("🟢 أولوية عادية", "prio_عادية");
      await ctx.reply("🎯 <b>حدد مستوى الأولوية:</b>", {
        reply_markup: kb,
        parse_mode: "HTML",
      });
      return;
    }

    if (state === "task_due") {
      await addTask({
        title: ctx.session.taskTitle!,
        description: ctx.session.taskDesc || "بدون وصف",
        priority: ctx.session.taskPrio || "متوسطة",
        due_date: text,
        created_by: ctx.from!.id,
      });
      ctx.session.state = null;
      const kb = new InlineKeyboard()
        .text("➕ إضافة مهمة أخرى", "t_add").row()
        .text("🔙 عودة للمهام", "m_tasks");
      await ctx.reply("✅ تم إدراج المهمة بنجاح ضمن دورة العمل.", { reply_markup: kb });
      return;
    }

    // --------- إفادة مهمة ---------
    if (state === "task_update") {
      await addTaskUpdate(ctx.session.taskIdForUpdate!, text, ctx.from!.id);
      ctx.session.state = null;
      const kb = new InlineKeyboard().text("🔙 معاينة المهمة", `t_view_${ctx.session.taskIdForUpdate}`);
      ctx.session.taskIdForUpdate = undefined;
      await ctx.reply("✅ تم توثيق الإفادة بنجاح وحفظها بالأرشيف.", { reply_markup: kb });
      return;
    }

    // --------- إضافة اجتماع ---------
    if (state === "meet_title") {
      if (text.length < 3) {
        await ctx.reply("⚠️ العنوان قصير جداً. حاول مرة أخرى:", { reply_markup: cancelKb() });
        return;
      }
      ctx.session.meetTitle = text;
      ctx.session.state = "meet_date";
      await ctx.reply("📅 <b>تاريخ وتوقيت الانعقاد:</b>", {
        reply_markup: cancelKb(),
        parse_mode: "HTML",
      });
      return;
    }

    if (state === "meet_date") {
      ctx.session.meetDate = text;
      ctx.session.state = "meet_loc";
      await ctx.reply("📍 <b>مكان الانعقاد / القاعة:</b>", {
        reply_markup: cancelKb(),
        parse_mode: "HTML",
      });
      return;
    }

    if (state === "meet_loc") {
      const mid = await addMeeting({
        title: ctx.session.meetTitle!,
        meeting_date: ctx.session.meetDate!,
        location: text,
        created_by: ctx.from!.id,
      });
      ctx.session.state = null;
      const kb = new InlineKeyboard()
        .text("➕ إضافة بند أعمال", `mt_add_item_${mid}`).row()
        .text("🔙 القائمة", "m_meets");
      await ctx.reply(`✅ تم تأسيس سجل الاجتماع رقم #${mid.slice(-4)}.`, { reply_markup: kb });
      return;
    }

    // --------- بند اجتماع ---------
    if (state === "meet_item_text") {
      const itype = ctx.session.taskTitle!; // نوع البند محفوظ هنا
      await addMeetingItem(ctx.session.meetId!, itype, text);
      ctx.session.state = null;
      const kb = new InlineKeyboard().text("🔙 استعراض الاجتماع", `mt_view_${ctx.session.meetId}`);
      await ctx.reply("✅ تم التوثيق بنجاح ضمن محضر الاجتماع.", { reply_markup: kb });
      return;
    }

    // --------- مقترح جديد ---------
    if (state === "prop_activity") {
      if (text.length < 5) {
        await ctx.reply("⚠️ الوصف قصير جداً. حاول مرة أخرى:", { reply_markup: cancelKb() });
        return;
      }
      ctx.session.propActivity = text;
      ctx.session.state = "prop_time";
      await ctx.reply("⏱ <b>حدد الإطار الزمني المقدر للتنفيذ:</b>", {
        reply_markup: cancelKb(),
        parse_mode: "HTML",
      });
      return;
    }

    if (state === "prop_time") {
      await addProposal({
        dept_id: ctx.session.deptId!,
        activity: ctx.session.propActivity!,
        proposed_time: text,
        created_by: ctx.from!.id,
      });
      ctx.session.state = null;
      const kb = new InlineKeyboard().text("🔙 إدارة المقترحات", "m_props");
      await ctx.reply("✅ تم إدراج المقترح ضمن بنك الأفكار التطويرية.", { reply_markup: kb });
      return;
    }

    // --------- إفادة مقترح ---------
    if (state === "prop_update") {
      await addProposalUpdate(ctx.session.propIdForUpdate!, text, ctx.from!.id);
      ctx.session.state = null;
      const kb = new InlineKeyboard().text("🔙 عودة للبطاقة", `p_view_${ctx.session.propIdForUpdate}`);
      ctx.session.propIdForUpdate = undefined;
      await ctx.reply("✅ تم قيد الإفادة بالسجل التاريخي.", { reply_markup: kb });
      return;
    }

    // --------- اسم إدارة ---------
    if (state === "dept_name") {
      if (!text) {
        await ctx.reply("⚠️ الاسم لا يمكن أن يكون فارغاً.", { reply_markup: cancelKb() });
        return;
      }
      await addDepartment(text);
      ctx.session.state = null;
      const kb = new InlineKeyboard().text("🔙 عودة للإدارات", "m_depts");
      await ctx.reply("✅ تم تعريف الإدارة بالنظام بنجاح.", { reply_markup: kb });
      return;
    }

    // --------- إضافة مستخدم ---------
    if (state === "user_add_id") {
      const uid = parseInt(text);
      if (isNaN(uid)) {
        await ctx.reply("⚠️ المعرف يجب أن يتكون من أرقام فقط.", { reply_markup: cancelKb() });
        return;
      }
      const existing = await getUser(uid);
      if (existing) {
        ctx.session.state = null;
        const kb = await mainMenuKb(ctx.from!.id);
        await ctx.reply("⚠️ حساب الموظف مسجل ومفعل مسبقاً بالنظام.", { reply_markup: kb });
        return;
      }
      ctx.session.targetUserId = uid;
      ctx.session.state = "user_perm_set";
      const kb = await permissionToggleKb(uid);
      await ctx.reply(`🔧 <b>لوحة التحكم في الصلاحيات</b> (رقم المستخدم: <code>${uid}</code>):`, {
        reply_markup: kb,
        parse_mode: "HTML",
      });
      return;
    }
  });

  // --------- الأولوية (Callback بعد task_desc) ---------
  bot.callbackQuery(/^prio_(.+)$/, async (ctx) => {
    const prio = ctx.match[1];
    ctx.session.taskPrio = prio;
    ctx.session.state = "task_due";
    await safeEdit(
      ctx,
      "📅 <b>أدخل الموعد النهائي (مثال: 2026-12-31):</b>",
      cancelKb()
    );
  });

  // ============================================================
  // معالجة المرفقات (صور ومستندات)
  // ============================================================
  bot.on(["message:document", "message:photo"], async (ctx) => {
    if (ctx.session.state !== "attach_file") return;
    const msg = ctx.message;
    let fid: string, fname: string, ftype: string;
    if (msg.document) {
      fid = msg.document.file_id;
      fname = msg.document.file_name || "document";
      ftype = "document";
    } else if (msg.photo) {
      fid = msg.photo[msg.photo.length - 1].file_id;
      fname = `IMG_${new Date().toISOString().replace(/[:.]/g, "_")}.jpg`;
      ftype = "photo";
    } else {
      return;
    }

    await addAttachment({
      file_id: fid,
      file_name: fname,
      file_type: ftype,
      ref_type: ctx.session.refType!,
      ref_id: ctx.session.refId!,
    });
    ctx.session.state = null;

    const kb = new InlineKeyboard();
    if (ctx.session.refType === "task") {
      kb.text("🔙 للمهمة المعنية", `t_view_${ctx.session.refId}`);
    } else {
      kb.text("🔙 لمحضر الاجتماع", `mt_view_${ctx.session.refId}`);
    }
    ctx.session.refType = undefined;
    ctx.session.refId = undefined;
    await ctx.reply("✅ تمت أرشفة المستند وربطه آلياً بالسجل المطلوب.", { reply_markup: kb });
  });

  return bot;
}

// ============================================================
// دالة مساعدة لتعديل الرسالة بأمان
// ============================================================
async function safeEdit(
  ctx: MyContext,
  text: string,
  replyMarkup: InlineKeyboard
): Promise<void> {
  try {
    await ctx.editMessageText(text, {
      reply_markup: replyMarkup,
      parse_mode: "HTML",
    });
    await ctx.answerCallbackQuery();
  } catch (e: unknown) {
    const error = e as Error;
    if (error.message?.includes("message is not modified")) {
      await ctx.answerCallbackQuery({ text: "⏳ أنت بالفعل في هذه الصفحة" });
    } else {
      console.error("Edit Error:", error.message);
      await ctx.answerCallbackQuery();
    }
  }
}

// استيراد deleteAllPermissions
import { deleteAllPermissions } from "./db";

export { createBot };
