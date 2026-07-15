const OFFICE_HUB_API = "http://localhost:8000";
const OFFICE_HUB_API_KEY = "b253ca1b038185185289506cd64642a1b8e478d86b09c8c58c8cad7faded8960";
const GMAIL_FETCH_TIMEOUT_MS = 45000;
const OFFICE_HUB_POST_TIMEOUT_MS = 600000;

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "INGEST_ATTACHMENT") {
    ingestAttachment(message)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "Attachment ingest failed.",
        });
      });

    return true;
  }

  if (message?.type === "EXTRACT_CHANGE_ORDER") {
    extractChangeOrder(message)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : "Change order extraction failed.",
        });
      });

    return true;
  }

  return false;
});

async function ingestAttachment({ url, filename, docType }) {
  const attachment = await downloadAttachment({ url, filename });
  return await postToOfficeHub({
    filename: attachment.filename,
    mimeType: attachment.mimeType,
    buffer: attachment.buffer,
    docType: docType || "auto",
  });
}

async function downloadAttachment({ url, filename }) {
  if (!url) {
    throw new Error("Missing Gmail attachment download URL.");
  }

  const resolvedFilename = sanitizeFilename(filename || "attachment.pdf");

  try {
    return await fetchAttachmentBytes(url, resolvedFilename);
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Gmail blocked extension upload.";
    throw new Error(
      `${reason} Office Hub did not download the file automatically. ` +
      "Open the attachment in Gmail or save it manually before uploading."
    );
  }
}

async function fetchAttachmentBytes(url, filename) {
  let response;
  try {
    response = await fetchWithRedirects(url);
  } catch (error) {
    throw new Error(
      error instanceof Error
        ? `Gmail attachment fetch failed: ${error.message}.`
        : "Gmail attachment fetch failed."
    );
  }

  if (!response.ok) {
    throw new Error(`Gmail attachment download failed: ${response.status}.`);
  }

  const dispositionFilename = filenameFromDisposition(response.headers.get("content-disposition"));
  const contentType = response.headers.get("content-type") || "application/pdf";
  const buffer = await response.arrayBuffer();

  return {
    filename: dispositionFilename || filename,
    mimeType: contentType,
    buffer,
  };
}

async function postToOfficeHub({ filename, mimeType, buffer, docType }) {
  const formData = new FormData();
  formData.append("file", new Blob([buffer], { type: mimeType || "application/pdf" }), filename);
  formData.append("doc_type", docType);

  const response = await fetch(`${OFFICE_HUB_API}/api/v1/ingest`, {
    method: "POST",
    headers: {
      "X-API-Key": OFFICE_HUB_API_KEY,
    },
    body: formData,
    signal: AbortSignal.timeout(OFFICE_HUB_POST_TIMEOUT_MS),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Office Hub ingest failed: ${response.status} ${errorText}`);
  }

  const result = await response.json();
  return {
    filename,
    ingest: result,
  };
}

async function extractChangeOrder({ emailBody }) {
  if (!emailBody) {
    throw new Error("Missing change order email body.");
  }

  const pendingChangeOrder = {
    emailBody,
    timestamp: new Date().toISOString(),
  };
  await chrome.storage.local.set({ pendingChangeOrder });
  await setPendingChangeOrderBadge(true);

  const response = await fetch(`${OFFICE_HUB_API}/api/v1/change-orders/extract`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": OFFICE_HUB_API_KEY,
    },
    body: JSON.stringify({ email_body: emailBody }),
    signal: AbortSignal.timeout(OFFICE_HUB_POST_TIMEOUT_MS),
  });

  if (!response.ok) {
    const errorText = await response.text();
    if (response.status === 401) {
      throw new Error(
        "Office Hub change order extract failed: API key rejected. Reload the Office Hub extension in Brave extensions and try again."
      );
    }
    throw new Error(`Office Hub change order extract failed: ${response.status} ${errorText}`);
  }

  const draft = await response.json();
  await chrome.storage.local.remove("pendingChangeOrder");
  await setPendingChangeOrderBadge(false);
  const draftParam = encodeURIComponent(JSON.stringify(draft));
  await chrome.tabs.create({
    url: `http://localhost:3000/change-orders/new?draft=${draftParam}`,
  });

  return { draft };
}

async function setPendingChangeOrderBadge(hasPending) {
  await chrome.action.setBadgeText({ text: hasPending ? "CO" : "" });
  if (hasPending) {
    await chrome.action.setBadgeBackgroundColor({ color: "#FAC775" });
    await chrome.action.setBadgeTextColor({ color: "#0f1117" });
  }
}

async function fetchWithRedirects(url) {
  const requestOptions = {
    mode: "cors",
    credentials: "include",
    redirect: "follow",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
    },
  };

  try {
    return await fetch(url, withTimeout(requestOptions, GMAIL_FETCH_TIMEOUT_MS));
  } catch (_error) {
    return await fetchWithManualRedirects(url);
  }
}

async function fetchWithManualRedirects(initialUrl) {
  let nextUrl = initialUrl;

  for (let redirectCount = 0; redirectCount < 5; redirectCount += 1) {
    const response = await fetch(nextUrl, {
      mode: "cors",
      credentials: "include",
      redirect: "manual",
      signal: AbortSignal.timeout(GMAIL_FETCH_TIMEOUT_MS),
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    });

    if (![301, 302, 303, 307, 308].includes(response.status)) {
      return response;
    }

    const location = response.headers.get("location");
    if (!location) {
      return response;
    }
    nextUrl = new URL(location, nextUrl).toString();
  }

  throw new Error("Gmail attachment redirect limit exceeded.");
}

function sanitizeFilename(filename) {
  return filename.replace(/[\\/:*?"<>|]/g, "-").trim() || "attachment.pdf";
}

function withTimeout(options, timeoutMs) {
  return {
    ...options,
    signal: AbortSignal.timeout(timeoutMs),
  };
}

function filenameFromDisposition(disposition) {
  if (!disposition) {
    return "";
  }

  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match) {
    return decodeURIComponent(utf8Match[1].replace(/^"|"$/g, ""));
  }

  const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
  return filenameMatch ? filenameMatch[1] : "";
}
