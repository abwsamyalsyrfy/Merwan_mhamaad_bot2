// src/index.ts
// ============================================================
// نقطة الدخول لـ Firebase Functions
// ============================================================
import * as admin from "firebase-admin";
import * as functions from "firebase-functions";
import { webhookCallback } from "grammy";
import { createBot } from "./bot";

// تهيئة Firebase Admin
admin.initializeApp();

// قراءة رمز البوت من Firebase Config
const BOT_TOKEN = functions.config().bot?.token || process.env.BOT_TOKEN || "";

if (!BOT_TOKEN) {
  console.error("❌ BOT_TOKEN not configured! Run: firebase functions:config:set bot.token=YOUR_TOKEN");
}

// إنشاء البوت
const bot = createBot(BOT_TOKEN);

// تهيئة الـ Webhook endpoint
export const telegramWebhook = functions
  .region("us-central1")
  .runWith({
    timeoutSeconds: 60,
    memory: "512MB",
  })
  .https.onRequest(webhookCallback(bot, "express"));

// Health Check endpoint
export const health = functions
  .region("us-central1")
  .https.onRequest((req, res) => {
    res.json({
      status: "healthy",
      timestamp: new Date().toISOString(),
      bot: BOT_TOKEN ? "configured" : "missing_token",
    });
  });
