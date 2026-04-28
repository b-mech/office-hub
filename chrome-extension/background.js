chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get({ autoMode: false }, ({ autoMode }) => {
    chrome.storage.sync.set({ autoMode: Boolean(autoMode) });
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "DOWNLOAD_ATTACHMENT") {
    return false;
  }

  downloadAttachment(message)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => {
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : "Attachment download failed.",
      });
    });

  return true;
});

async function downloadAttachment({ url, filename }) {
  if (!url) {
    throw new Error("Missing Gmail attachment download URL.");
  }

  const response = await fetch(url, {
    credentials: "include",
    redirect: "follow",
  });

  if (!response.ok) {
    throw new Error(`Gmail attachment download failed: ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "application/pdf";
  const resolvedFilename = filename || filenameFromDisposition(response.headers.get("content-disposition"));
  const buffer = await response.arrayBuffer();

  return {
    filename: resolvedFilename || "attachment.pdf",
    mimeType: contentType,
    base64: arrayBufferToBase64(buffer),
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

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}
