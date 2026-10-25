"""Offline-capable field activity capture shell and same-origin client."""

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["CRM field activity capture"])

_PAGE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ثبت فعالیت میدانی | فانل CRM</title>
  <style>
    :root{font-family:system-ui,sans-serif;color:#182b5e;background:#f4f6fb}*{box-sizing:border-box}body{margin:0;padding:24px;max-width:900px;margin-inline:auto}main{background:#fff;border:1px solid #d9dfec;border-radius:16px;padding:24px;box-shadow:0 8px 24px #182b5e12}h1{font-size:1.5rem;margin-top:0}p{line-height:1.8}.notice{background:#eef3ff;padding:12px 16px;border-radius:10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}label{display:grid;gap:6px;font-weight:600}input,select,button{font:inherit;border:1px solid #aab5cc;border-radius:8px;padding:10px;min-height:44px}button{background:#182b5e;color:#fff;border:0;cursor:pointer}button:disabled{opacity:.55;cursor:wait}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}#status{min-height:28px}ul{padding:0;list-style:none}li{border-top:1px solid #e1e5ee;padding:12px 0;display:grid;gap:5px}.muted{color:#52627e;font-size:.92rem}.good{color:#176b45}.warn{color:#9a4f00}@media(max-width:520px){body{padding:10px}main{padding:16px}}
  </style>
  <script src="/assets/crm-activity-capture.js" defer></script>
</head>
<body>
<main>
  <h1>ثبت فعالیت میدانی</h1>
  <p class="notice">پس از بازکردن این صفحه، در قطع اینترنت هم می‌توانید بازدید، تماس یا پیگیری را ثبت کنید. داده‌ها فقط روی همین مرورگر نگه داشته می‌شوند تا همگام شوند؛ توضیحات شخصی مشتری را در شناسه‌ها وارد نکنید.</p>
  <p id="connection-status" aria-live="polite" class="muted">در حال بررسی اتصال…</p>
  <form id="activity-form">
    <div class="grid">
      <label for="workspace-id">شناسهٔ فضای کاری<input id="workspace-id" autocomplete="off" required pattern="[0-9a-fA-F-]{36}"></label>
      <label for="profile-id">شناسهٔ پروفایل CRM<input id="profile-id" autocomplete="off" required pattern="[0-9a-fA-F-]{36}"></label>
      <label for="campaign-id">شناسهٔ کمپین (اختیاری)<input id="campaign-id" autocomplete="off" pattern="[0-9a-fA-F-]{36}"></label>
      <label for="activity-type">نوع فعالیت<select id="activity-type"><option value="field.visit">بازدید</option><option value="phone.call">تماس تلفنی</option><option value="follow_up">پیگیری</option></select></label>
      <label for="channel">کانال<select id="channel"><option value="field">میدانی</option><option value="phone">تلفنی</option><option value="store">فروشگاه</option><option value="other">سایر</option></select></label>
      <label for="occurred-at">زمان انجام فعالیت<input id="occurred-at" type="datetime-local" required></label>
    </div>
    <div class="actions"><button id="save-activity" type="submit">ثبت فعالیت</button><button id="sync-activities" type="button">همگام‌سازی دوباره</button></div>
  </form>
  <h2>صف همگام‌سازی</h2>
  <p id="status" role="status" aria-live="polite"></p>
  <ul id="activity-queue" aria-live="polite"></ul>
</main>
</body>
</html>"""

_CLIENT_SCRIPT = r"""(() => {
  const DB_NAME = "funnel-crm-field-activities";
  const STORE_NAME = "activities";
  const byId = (id) => document.getElementById(id);
  const statusNode = byId("status");
  const queueNode = byId("activity-queue");
  let syncing = false;
  const statusLabels = { queued: "در انتظار همگام‌سازی", synced: "همگام‌شده", needs_attention: "نیازمند رسیدگی" };
  function setStatus(message, isError = false) {
    statusNode.textContent = message;
    statusNode.className = isError ? "warn" : "good";
  }
  function openDb() {
    if (!window.indexedDB) return Promise.reject(new Error("ذخیره‌سازی آفلاین در این مرورگر در دسترس نیست."));
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: "source_event_id" });
          store.createIndex("workspace_id", "workspace_id", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("صف محلی باز نشد."));
    });
  }
  function requestResult(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("عملیات صف محلی ناموفق بود."));
    });
  }
  function transactionDone(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error || new Error("ثبت محلی کامل نشد."));
      transaction.onabort = () => reject(transaction.error || new Error("ثبت محلی لغو شد."));
    });
  }
  async function storeItem(item) {
    const db = await openDb();
    try {
      const transaction = db.transaction(STORE_NAME, "readwrite");
      const committed = transactionDone(transaction);
      await Promise.all([requestResult(transaction.objectStore(STORE_NAME).put(item)), committed]);
    }
    finally { db.close(); }
  }
  async function itemsForWorkspace(workspaceId) {
    if (!workspaceId) return [];
    const db = await openDb();
    try {
      const store = db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME);
      return await requestResult(store.index("workspace_id").getAll(workspaceId));
    } finally { db.close(); }
  }
  function render(items) {
    queueNode.replaceChildren();
    items.sort((a, b) => b.created_at.localeCompare(a.created_at)).forEach((item) => {
      const row = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${item.activity_label} · ${statusLabels[item.status] || statusLabels.queued}`;
      const details = document.createElement("span");
      details.className = "muted";
      details.textContent = `${item.profile_id} · ${new Date(item.occurred_at).toLocaleString("fa-IR")}`;
      row.append(title, details);
      if (item.last_error) {
        const error = document.createElement("span");
        error.className = "warn";
        error.textContent = item.last_error;
        row.append(error);
      }
      queueNode.appendChild(row);
    });
  }
  async function refresh() {
    try { render(await itemsForWorkspace(byId("workspace-id").value.trim())); }
    catch (error) { setStatus(error.message || "خواندن صف محلی ناموفق بود.", true); }
  }
  async function syncQueue() {
    if (syncing || !navigator.onLine) return;
    syncing = true;
    byId("sync-activities").disabled = true;
    try {
      const pending = (await itemsForWorkspace(byId("workspace-id").value.trim())).filter((item) => item.status === "queued");
      for (const item of pending) {
        try {
          const response = await fetch(`/api/v1/crm/profiles/${encodeURIComponent(item.profile_id)}/activities/sync`, {
            method: "POST", credentials: "same-origin",
            headers: { "Accept": "application/json", "Content-Type": "application/json", "X-Workspace-ID": item.workspace_id },
            body: JSON.stringify({
              source_event_id: item.source_event_id, campaign_id: item.campaign_id,
              activity_type: item.activity_type, channel: item.channel,
              source_record_id: null, occurred_at: item.occurred_at,
            }),
          });
          let payload = {};
          try { payload = await response.json(); } catch (_) {}
          if (response.ok) {
            item.status = "synced";
            item.activity_id = payload.activity?.id || null;
            item.last_error = "";
          } else if ([401, 403, 404, 409, 422].includes(response.status)) {
            item.status = "needs_attention";
            item.last_error = typeof payload.detail === "string" ? payload.detail : `خطای قابل‌رسیدگی (${response.status})`;
          } else {
            item.last_error = `همگام‌سازی موقتاً ناموفق بود (${response.status})؛ شناسهٔ رویداد برای تلاش بعدی حفظ شد.`;
          }
          await storeItem(item);
        } catch (_) {
          item.last_error = "اتصال برقرار نشد؛ رکورد با همان شناسه برای تلاش بعدی نگه داشته شد.";
          await storeItem(item);
        }
      }
      await refresh();
      if (!pending.length) setStatus("فعالیت منتظری برای همگام‌سازی وجود ندارد.");
      else setStatus("بررسی صف انجام شد؛ وضعیت هر فعالیت در فهرست مشخص است.");
    } catch (error) {
      setStatus(error.message || "همگام‌سازی صف انجام نشد.", true);
    } finally {
      syncing = false;
      byId("sync-activities").disabled = false;
    }
  }
  function updateConnection() {
    const online = navigator.onLine;
    byId("connection-status").textContent = online ? "اتصال برقرار است؛ فعالیت‌های منتظر به‌صورت خودکار ارسال می‌شوند." : "آفلاین هستید؛ فعالیت‌ها روی همین مرورگر صف می‌شوند.";
    byId("connection-status").className = online ? "good" : "warn";
    if (online) syncQueue();
  }
  function localInputTime() {
    const now = new Date();
    return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }
  byId("activity-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const workspaceId = byId("workspace-id").value.trim();
    const profileId = byId("profile-id").value.trim();
    const campaignId = byId("campaign-id").value.trim() || null;
    if (!byId("activity-form").reportValidity()) return;
    try {
      const activityType = byId("activity-type").value;
      const item = {
        source_event_id: crypto.randomUUID(), workspace_id: workspaceId, profile_id: profileId,
        campaign_id: campaignId, activity_type: activityType, channel: byId("channel").value,
        occurred_at: new Date(byId("occurred-at").value).toISOString(),
        activity_label: byId("activity-type").selectedOptions[0].textContent,
        created_at: new Date().toISOString(), status: "queued", last_error: "",
      };
      await storeItem(item);
      byId("activity-form").reset();
      byId("workspace-id").value = workspaceId;
      byId("occurred-at").value = localInputTime();
      setStatus("فعالیت در صف محلی ثبت شد؛ شناسهٔ یکتای آن تا تأیید سرور حفظ می‌شود.");
      await refresh();
      if (navigator.onLine) syncQueue();
    } catch (error) { setStatus(error.message || "ثبت محلی فعالیت ناموفق بود.", true); }
  });
  byId("sync-activities").addEventListener("click", syncQueue);
  byId("workspace-id").addEventListener("change", refresh);
  window.addEventListener("online", updateConnection);
  window.addEventListener("offline", updateConnection);
  if (window.isSecureContext && navigator.serviceWorker) {
    navigator.serviceWorker.register("/assets/crm-activity-capture-sw.js", { scope: "/" })
      .catch(() => { byId("connection-status").textContent += " بارگذاری آفلاین صفحه برای دفعات بعد فعال نشد."; });
  }
  byId("occurred-at").value = localInputTime();
  const requestedWorkspace = new URLSearchParams(window.location.search).get("workspace_id");
  if (requestedWorkspace) byId("workspace-id").value = requestedWorkspace;
  refresh();
  updateConnection();
})();"""

_SERVICE_WORKER_SCRIPT = r"""const CACHE_NAME = "funnel-crm-activity-shell-v1";
const PAGE_PATH = "/workspace/crm-activity-capture";
const SCRIPT_PATH = "/assets/crm-activity-capture.js";
const SHELL = [PAGE_PATH, SCRIPT_PATH];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    for (const path of SHELL) {
      const response = await fetch(path, { cache: "reload", credentials: "same-origin" });
      if (!response.ok) throw new Error("Could not cache the offline activity shell");
      await cache.put(new URL(path, self.location.origin), response.clone());
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith("funnel-crm-activity-shell-") && name !== CACHE_NAME)
      .map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname === PAGE_PATH && request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const key = new URL(PAGE_PATH, self.location.origin);
      try {
        const response = await fetch(request);
        if (response.ok) await cache.put(key, response.clone());
        return response;
      } catch (_) {
        return await cache.match(key) || new Response("برای استفادهٔ آفلاین، صفحه را یک‌بار هنگام اتصال باز کنید.", {
          status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
        });
      }
    })());
    return;
  }
  if (url.pathname === SCRIPT_PATH) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const key = new URL(SCRIPT_PATH, self.location.origin);
      const cached = await cache.match(key);
      const update = fetch(request).then(async (response) => {
        if (response.ok) await cache.put(key, response.clone());
        return response;
      }).catch(() => null);
      if (cached) { event.waitUntil(update); return cached; }
      return await update || new Response("اسکریپت ثبت آفلاین در دسترس نیست.", {
        status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    })());
  }
});"""

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/workspace/crm-activity-capture", response_class=HTMLResponse)
async def crm_activity_capture_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers=_SECURITY_HEADERS)


@router.get("/assets/crm-activity-capture.js")
async def crm_activity_capture_script() -> Response:
    return Response(
        _CLIENT_SCRIPT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/assets/crm-activity-capture-sw.js")
async def crm_activity_capture_service_worker() -> Response:
    return Response(
        _SERVICE_WORKER_SCRIPT,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
            "X-Content-Type-Options": "nosniff",
        },
    )
