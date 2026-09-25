// src/db.ts
// ============================================================
// طبقة قاعدة البيانات - Firestore (بديل SQLite)
// ============================================================
import * as admin from "firebase-admin";

export const firestore = admin.firestore();

// ============================================================
// Users
// ============================================================
export interface UserRecord {
  user_id: number;
  full_name: string;
  username: string;
  role: string;
}

export async function getUser(userId: number): Promise<UserRecord | null> {
  const doc = await firestore.collection("users").doc(String(userId)).get();
  return doc.exists ? (doc.data() as UserRecord) : null;
}

export async function upsertUser(user: UserRecord): Promise<void> {
  const ref = firestore.collection("users").doc(String(user.user_id));
  await ref.set(user, { merge: true });
}

export async function getAllUsers(): Promise<UserRecord[]> {
  const snap = await firestore.collection("users").orderBy("user_id").get();
  return snap.docs.map((d) => d.data() as UserRecord);
}

export async function deleteUser(userId: number): Promise<void> {
  await firestore.collection("users").doc(String(userId)).delete();
}

export async function countUsers(): Promise<number> {
  const snap = await firestore.collection("users").count().get();
  return snap.data().count;
}

// ============================================================
// Permissions
// ============================================================
export async function getUserPermissions(userId: number): Promise<string[]> {
  const snap = await firestore
    .collection("user_permissions")
    .where("user_id", "==", userId)
    .get();
  return snap.docs.map((d) => d.data().permission as string);
}

export async function setPermission(
  userId: number,
  perm: string,
  value: boolean
): Promise<void> {
  const ref = firestore
    .collection("user_permissions")
    .doc(`${userId}_${perm}`);
  if (value) {
    await ref.set({ user_id: userId, permission: perm });
  } else {
    await ref.delete();
  }
}

export async function deleteAllPermissions(userId: number): Promise<void> {
  const snap = await firestore
    .collection("user_permissions")
    .where("user_id", "==", userId)
    .get();
  const batch = firestore.batch();
  snap.docs.forEach((d) => batch.delete(d.ref));
  await batch.commit();
}

// ============================================================
// Departments
// ============================================================
export interface Department {
  id: string;
  name: string;
}

export async function getAllDepartments(): Promise<Department[]> {
  const snap = await firestore
    .collection("departments")
    .orderBy("name")
    .get();
  return snap.docs.map((d) => ({ id: d.id, name: d.data().name as string }));
}

export async function addDepartment(name: string): Promise<string> {
  // Check if already exists
  const existing = await firestore
    .collection("departments")
    .where("name", "==", name)
    .limit(1)
    .get();
  if (!existing.empty) return existing.docs[0].id;
  const ref = await firestore.collection("departments").add({ name });
  return ref.id;
}

export async function deleteDepartment(id: string): Promise<void> {
  await firestore.collection("departments").doc(id).delete();
}

export async function getDepartment(id: string): Promise<Department | null> {
  const doc = await firestore.collection("departments").doc(id).get();
  return doc.exists ? { id: doc.id, name: doc.data()!.name as string } : null;
}

export async function countProposalsByDept(deptId: string): Promise<number> {
  const snap = await firestore
    .collection("proposals")
    .where("dept_id", "==", deptId)
    .count()
    .get();
  return snap.data().count;
}

// ============================================================
// Tasks
// ============================================================
export interface Task {
  id: string;
  title: string;
  description: string;
  priority: string;
  status: string;
  due_date: string;
  created_by: number;
  created_at: string;
}

export async function addTask(data: Omit<Task, "id" | "created_at" | "status">): Promise<string> {
  const ref = await firestore.collection("tasks").add({
    ...data,
    status: "قيد التنفيذ",
    created_at: new Date().toISOString(),
  });
  return ref.id;
}

export async function getTask(id: string): Promise<Task | null> {
  const doc = await firestore.collection("tasks").doc(id).get();
  return doc.exists ? ({ id: doc.id, ...doc.data() } as Task) : null;
}

export async function getTasksByStatus(status: string): Promise<Task[]> {
  const snap = await firestore
    .collection("tasks")
    .where("status", "==", status)
    .orderBy("created_at", "desc")
    .limit(40)
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as Task));
}

export async function updateTaskStatus(id: string, status: string): Promise<void> {
  await firestore.collection("tasks").doc(id).update({ status });
}

export async function deleteTask(id: string): Promise<void> {
  await firestore.collection("tasks").doc(id).delete();
}

export async function getAllTasksForReport(): Promise<Task[]> {
  const snap = await firestore.collection("tasks").get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as Task));
}

export async function countTasks(): Promise<number> {
  const snap = await firestore.collection("tasks").count().get();
  return snap.data().count;
}

export async function countTasksByStatus(status: string): Promise<number> {
  const snap = await firestore
    .collection("tasks")
    .where("status", "==", status)
    .count()
    .get();
  return snap.data().count;
}

// ============================================================
// Task Updates
// ============================================================
export interface TaskUpdate {
  id: string;
  task_id: string;
  update_text: string;
  created_by: number;
  created_at: string;
  full_name?: string;
}

export async function addTaskUpdate(
  taskId: string,
  text: string,
  userId: number
): Promise<void> {
  await firestore.collection("task_updates").add({
    task_id: taskId,
    update_text: text,
    created_by: userId,
    created_at: new Date().toISOString(),
  });
}

export async function getTaskUpdates(taskId: string): Promise<TaskUpdate[]> {
  const snap = await firestore
    .collection("task_updates")
    .where("task_id", "==", taskId)
    .orderBy("created_at", "asc")
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as TaskUpdate));
}

export async function countTaskUpdates(taskId: string): Promise<number> {
  const snap = await firestore
    .collection("task_updates")
    .where("task_id", "==", taskId)
    .count()
    .get();
  return snap.data().count;
}

export async function deleteTaskUpdates(taskId: string): Promise<void> {
  const snap = await firestore
    .collection("task_updates")
    .where("task_id", "==", taskId)
    .get();
  const batch = firestore.batch();
  snap.docs.forEach((d) => batch.delete(d.ref));
  await batch.commit();
}

export async function getAllTaskUpdatesForReport(): Promise<TaskUpdate[]> {
  const snap = await firestore
    .collection("task_updates")
    .orderBy("created_at", "desc")
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as TaskUpdate));
}

// ============================================================
// Meetings
// ============================================================
export interface Meeting {
  id: string;
  title: string;
  meeting_date: string;
  location: string;
  created_by: number;
  created_at: string;
}

export async function addMeeting(
  data: Omit<Meeting, "id" | "created_at">
): Promise<string> {
  const ref = await firestore.collection("meetings").add({
    ...data,
    created_at: new Date().toISOString(),
  });
  return ref.id;
}

export async function getMeeting(id: string): Promise<Meeting | null> {
  const doc = await firestore.collection("meetings").doc(id).get();
  return doc.exists ? ({ id: doc.id, ...doc.data() } as Meeting) : null;
}

export async function getAllMeetings(): Promise<Meeting[]> {
  const snap = await firestore
    .collection("meetings")
    .orderBy("created_at", "desc")
    .limit(20)
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as Meeting));
}

export async function deleteMeeting(id: string): Promise<void> {
  await firestore.collection("meetings").doc(id).delete();
}

export async function countMeetings(): Promise<number> {
  const snap = await firestore.collection("meetings").count().get();
  return snap.data().count;
}

// ============================================================
// Meeting Items
// ============================================================
export interface MeetingItem {
  id: string;
  meeting_id: string;
  item_type: string;
  item_text: string;
}

export async function addMeetingItem(
  meetingId: string,
  itemType: string,
  itemText: string
): Promise<void> {
  await firestore.collection("meeting_items").add({
    meeting_id: meetingId,
    item_type: itemType,
    item_text: itemText,
  });
}

export async function getMeetingItems(meetingId: string): Promise<MeetingItem[]> {
  const snap = await firestore
    .collection("meeting_items")
    .where("meeting_id", "==", meetingId)
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as MeetingItem));
}

export async function deleteMeetingItems(meetingId: string): Promise<void> {
  const snap = await firestore
    .collection("meeting_items")
    .where("meeting_id", "==", meetingId)
    .get();
  const batch = firestore.batch();
  snap.docs.forEach((d) => batch.delete(d.ref));
  await batch.commit();
}

// ============================================================
// Proposals
// ============================================================
export interface Proposal {
  id: string;
  dept_id: string;
  activity: string;
  proposed_time: string;
  status: string;
  converted_to_task?: string;
  converted_to_meeting?: string;
  created_by: number;
  created_at: string;
}

export async function addProposal(
  data: Omit<Proposal, "id" | "created_at" | "status">
): Promise<string> {
  const ref = await firestore.collection("proposals").add({
    ...data,
    status: "مقترح",
    created_at: new Date().toISOString(),
  });
  return ref.id;
}

export async function getProposal(id: string): Promise<Proposal | null> {
  const doc = await firestore.collection("proposals").doc(id).get();
  return doc.exists ? ({ id: doc.id, ...doc.data() } as Proposal) : null;
}

export async function getProposalsByDept(deptId: string): Promise<Proposal[]> {
  const snap = await firestore
    .collection("proposals")
    .where("dept_id", "==", deptId)
    .orderBy("created_at", "desc")
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as Proposal));
}

export async function updateProposalStatus(
  id: string,
  status: string,
  extra?: Record<string, string>
): Promise<void> {
  await firestore
    .collection("proposals")
    .doc(id)
    .update({ status, ...(extra || {}) });
}

export async function deleteProposal(id: string): Promise<void> {
  await firestore.collection("proposals").doc(id).delete();
}

export async function countProposals(): Promise<number> {
  const snap = await firestore.collection("proposals").count().get();
  return snap.data().count;
}

export async function getAllProposalsForReport(): Promise<Proposal[]> {
  const snap = await firestore.collection("proposals").get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as Proposal));
}

// ============================================================
// Proposal Updates
// ============================================================
export interface ProposalUpdate {
  id: string;
  proposal_id: string;
  update_text: string;
  created_by: number;
  created_at: string;
  full_name?: string;
}

export async function addProposalUpdate(
  propId: string,
  text: string,
  userId: number
): Promise<void> {
  await firestore.collection("proposal_updates").add({
    proposal_id: propId,
    update_text: text,
    created_by: userId,
    created_at: new Date().toISOString(),
  });
}

export async function getProposalUpdates(propId: string): Promise<ProposalUpdate[]> {
  const snap = await firestore
    .collection("proposal_updates")
    .where("proposal_id", "==", propId)
    .orderBy("created_at", "asc")
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as ProposalUpdate));
}

export async function deleteProposalUpdates(propId: string): Promise<void> {
  const snap = await firestore
    .collection("proposal_updates")
    .where("proposal_id", "==", propId)
    .get();
  const batch = firestore.batch();
  snap.docs.forEach((d) => batch.delete(d.ref));
  await batch.commit();
}

// ============================================================
// Attachments
// ============================================================
export interface Attachment {
  id: string;
  file_id: string;
  file_name: string;
  file_type: string;
  ref_type: string;
  ref_id: string;
  uploaded_at: string;
}

export async function addAttachment(
  data: Omit<Attachment, "id" | "uploaded_at">
): Promise<string> {
  const ref = await firestore.collection("attachments").add({
    ...data,
    uploaded_at: new Date().toISOString(),
  });
  return ref.id;
}

export async function getAttachment(id: string): Promise<Attachment | null> {
  const doc = await firestore.collection("attachments").doc(id).get();
  return doc.exists ? ({ id: doc.id, ...doc.data() } as Attachment) : null;
}

export async function getRecentAttachments(): Promise<Attachment[]> {
  const snap = await firestore
    .collection("attachments")
    .orderBy("uploaded_at", "desc")
    .limit(10)
    .get();
  return snap.docs.map((d) => ({ id: d.id, ...d.data() } as Attachment));
}

export async function deleteAttachment(id: string): Promise<void> {
  await firestore.collection("attachments").doc(id).delete();
}

export async function deleteAttachmentsByRef(
  refType: string,
  refId: string
): Promise<void> {
  const snap = await firestore
    .collection("attachments")
    .where("ref_type", "==", refType)
    .where("ref_id", "==", refId)
    .get();
  const batch = firestore.batch();
  snap.docs.forEach((d) => batch.delete(d.ref));
  await batch.commit();
}

export async function countAttachments(): Promise<number> {
  const snap = await firestore.collection("attachments").count().get();
  return snap.data().count;
}
