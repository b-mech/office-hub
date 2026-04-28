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

  const resolvedFilename = sanitizeFilename(filename || "attachment.pdf");

  try {
    return await fetchAttachmentBytes(url, resolvedFilename);
  } catch (error) {
    const download = await downloadNative(url, resolvedFilename);
    const reason = error instanceof Error ? error.message : "Gmail blocked extension upload.";
    return {
      downloaded: true,
      downloadId: download.id,
      filename: download.filename || resolvedFilename,
      error: (
        `${reason} Chrome downloaded "${resolvedFilename}" to Downloads/Office Hub. ` +
        "Open Office Hub and upload that file manually."
      ),
    };
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
    base64: arrayBufferToBase64(buffer),
  };
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
    return await fetch(url, requestOptions);
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

function downloadNative(url, filename) {
  return new Promise((resolve, reject) => {
    chrome.downloads.download(
      {
        url,
        filename: `Office Hub/${filename}`,
        conflictAction: "uniquify",
        saveAs: false,
      },
      (downloadId) => {
        const runtimeError = chrome.runtime.lastError;
        if (runtimeError || downloadId === undefined) {
          reject(new Error(runtimeError?.message || "Chrome native download failed."));
          return;
        }

        waitForDownload(downloadId).then(resolve).catch(reject);
      }
    );
  });
}

function waitForDownload(downloadId) {
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      chrome.downloads.onChanged.removeListener(listener);
      reject(new Error("Chrome native download timed out."));
    }, 120000);

    function listener(delta) {
      if (delta.id !== downloadId) {
        return;
      }

      if (delta.error?.current) {
        clearTimeout(timeoutId);
        chrome.downloads.onChanged.removeListener(listener);
        reject(new Error(`Chrome native download failed: ${delta.error.current}.`));
        return;
      }

      if (delta.state?.current === "complete") {
        clearTimeout(timeoutId);
        chrome.downloads.onChanged.removeListener(listener);
        chrome.downloads.search({ id: downloadId }, ([item]) => {
          resolve({
            id: downloadId,
            filename: item?.filename || "",
          });
        });
      }
    }

    chrome.downloads.onChanged.addListener(listener);
  });
}

function sanitizeFilename(filename) {
  return filename.replace(/[\\/:*?"<>|]/g, "-").trim() || "attachment.pdf";
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
