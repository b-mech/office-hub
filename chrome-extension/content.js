// content.js
const OFFICE_HUB_API = "http://localhost:8000";
const OFFICE_HUB_APP = "http://localhost:3000";
const INGEST_RESPONSE_TIMEOUT_MS = 150000;

let observer = null;
let scanTimer = null;
let currentMessageKey = "";
let processedAttachmentKeys = new Set();
let selectedAttachmentKeys = new Set();
let renderedAttachmentSignature = "";

init();

function init() {
  chrome.storage.sync.get({ autoMode: false }, () => {
    observeGmail();
    scheduleScan();
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName === "sync" && changes.autoMode) {
      processedAttachmentKeys = new Set();
      scheduleScan();
    }
  });
}

function observeGmail() {
  if (observer) observer.disconnect();
  observer = new MutationObserver(() => scheduleScan());
  observer.observe(document.body, { childList: true, subtree: true });
}

function scheduleScan() {
  window.clearTimeout(scanTimer);
  scanTimer = window.setTimeout(scanOpenEmail, 500);
}

async function scanOpenEmail() {
  const messageRoot = findOpenMessageRoot();
  if (!messageRoot) { removePanel(); return; }

  const messageKey = getMessageKey(messageRoot);
  if (messageKey !== currentMessageKey) {
    currentMessageKey = messageKey;
    processedAttachmentKeys = new Set();
    selectedAttachmentKeys = new Set();
    renderedAttachmentSignature = "";
    removePanel();
    removeSummaries();
  }

  const attachments = findPdfAttachments(messageRoot);
  if (attachments.length === 0) {
    selectedAttachmentKeys = new Set();
    renderedAttachmentSignature = "";
    removePanel();
    return;
  }

  const { autoMode } = await chrome.storage.sync.get({ autoMode: false });
  renderPanel(attachments, messageRoot);

  if (autoMode) {
    const panel = document.querySelector(".office-hub-panel");
    setStatus(panel, "Auto mode on. Sending detected PDFs...");
    const { sent, failed } = await autoIngest(attachments, messageRoot);
    if (failed > 0) {
      setStatus(panel, `${failed} file${failed !== 1 ? "s" : ""} failed in auto mode.`);
    } else if (sent > 0) {
      setStatus(panel, `${sent} file${sent !== 1 ? "s" : ""} sent in auto mode.`);
    } else {
      setStatus(panel, "Auto mode on. PDFs already sent.");
    }
  }
}

// ─── Gmail DOM helpers ────────────────────────────────────────────────────────

function findOpenMessageRoot() {
  const conversation = document.querySelector('div[role="main"]');
  if (!conversation) return null;
  const expandedMessages = Array.from(
    conversation.querySelectorAll('div[role="listitem"], .adn, .gs')
  );
  const messagesWithPdfAttachments = expandedMessages.filter(hasPdfAttachmentMarker);
  return messagesWithPdfAttachments.at(-1) || conversation;
}

function getMessageKey(messageRoot) {
  const subject = document.querySelector("h2[data-thread-perm-id], h2.hP, h2")?.textContent || "";
  const date = messageRoot.querySelector("[title][alt], [title]")?.getAttribute("title") || "";
  return `${location.href}|${subject.trim()}|${date}`;
}

function hasPdfAttachmentMarker(node) {
  const downloadNodes = Array.from(node.querySelectorAll("[download_url]"));
  if (downloadNodes.some((downloadNode) => {
    const raw = downloadNode.getAttribute("download_url") || "";
    return raw.startsWith("application/pdf:");
  })) {
    return true;
  }

  const links = Array.from(node.querySelectorAll("a[href]"));
  return links.some((link) => {
    const href = link.getAttribute("href") || "";
    if (!looksLikeAttachmentLink(href)) return false;

    const labels = ["aria-label", "data-tooltip", "title"]
      .map((attr) => link.getAttribute(attr) || "")
      .join(" ");
    return /\.pdf\b/i.test(labels) || /\.pdf\b/i.test(href);
  });
}

// ─── PDF attachment detection ─────────────────────────────────────────────────

function findPdfAttachments(messageRoot) {
  // Strategy: find elements with download_url containing application/pdf,
  // which is Gmail's canonical attachment marker. Deduplicate by URL only
  // (not filename) to avoid the preview/download duplicate problem.
  const byUrl = new Map();

  const nodes = Array.from(messageRoot.querySelectorAll("[download_url]"));
  for (const node of nodes) {
    const raw = node.getAttribute("download_url") || "";
    // Gmail format: "application/pdf:filename.pdf:https://..."
    if (!raw.startsWith("application/pdf:")) continue;

    const parts = raw.split(":");
    const mimeType = parts[0];               // application/pdf
    const rawFilename = parts[1] || "";      // filename from download_url attribute
    const url = parts.slice(2).join(":");    // https://...

    if (!url) continue;

    // Clean the filename — use only the download_url part, not textContent
    const filename = cleanFilename(rawFilename) || "attachment.pdf";

    if (!byUrl.has(url)) {
      byUrl.set(url, { filename, url, key: url });
    }
  }

  // Fallback: href-based links for attachments without download_url
  if (byUrl.size === 0) {
    const links = Array.from(messageRoot.querySelectorAll("a[href]"));
    for (const link of links) {
      const href = link.getAttribute("href") || "";
      if (!looksLikeAttachmentLink(href)) continue;

      const filename = extractFilenameFromLink(link);
      if (!isPdfFilename(filename)) continue;

      const url = new URL(href, location.origin).toString();
      if (!byUrl.has(url)) {
        byUrl.set(url, { filename, url, key: url });
      }
    }
  }

  return Array.from(byUrl.values());
}

function looksLikeAttachmentLink(href) {
  return (
    href.includes("disp=attd") ||
    href.includes("view=att") ||
    href.includes("attid=")
  );
}

function extractFilenameFromLink(link) {
  // Try aria-label or data-tooltip first — these are clean
  for (const attr of ["aria-label", "data-tooltip", "title"]) {
    const val = link.getAttribute(attr) || "";
    const match = val.match(/([^/\\]+\.pdf)/i);
    if (match) return cleanFilename(match[1]);
  }
  // Avoid using textContent — it concatenates preview/download/filename
  return "attachment.pdf";
}

function isPdfFilename(filename) {
  return filename.toLowerCase().endsWith(".pdf");
}

function cleanFilename(filename) {
  return decodeFilename(filename || "")
    .replace(/^(download|open|preview|attachment)\s+/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function decodeFilename(filename) {
  try {
    return decodeURIComponent(filename);
  } catch (_error) {
    return filename;
  }
}

// ─── Panel UI ─────────────────────────────────────────────────────────────────

function renderPanel(attachments, messageRoot) {
  const attachmentSignature = attachments.map((attachment) => attachment.key).join("|");
  const existingPanel = document.querySelector(".office-hub-panel");
  if (existingPanel && attachmentSignature === renderedAttachmentSignature) {
    return;
  }

  if (selectedAttachmentKeys.size === 0) {
    selectedAttachmentKeys = new Set(attachments.map((attachment) => attachment.key));
  } else {
    const availableKeys = new Set(attachments.map((attachment) => attachment.key));
    selectedAttachmentKeys = new Set(
      Array.from(selectedAttachmentKeys).filter((key) => availableKeys.has(key))
    );
  }

  removePanel();
  renderedAttachmentSignature = attachmentSignature;

  const panel = document.createElement("aside");
  panel.className = "office-hub-panel";
  document.body.appendChild(panel);

  // Header
  const header = document.createElement("div");
  header.className = "office-hub-panel-header";
  const title = document.createElement("span");
  title.className = "office-hub-panel-title";
  title.textContent = "Office Hub";
  const closeBtn = document.createElement("button");
  closeBtn.className = "office-hub-panel-close";
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", removePanel);
  header.append(title, closeBtn);
  panel.appendChild(header);

  // Subtitle
  const subtitle = document.createElement("p");
  subtitle.className = "office-hub-panel-subtitle";
  subtitle.textContent = `${attachments.length} PDF${attachments.length !== 1 ? "s" : ""} detected`;
  panel.appendChild(subtitle);

  // Attachment rows — checkbox + filename only, no type dropdown
  const list = document.createElement("div");
  list.className = "office-hub-list";

  for (const attachment of attachments) {
    const row = document.createElement("label");
    row.className = "office-hub-row";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "office-hub-checkbox";
    checkbox.checked = selectedAttachmentKeys.has(attachment.key);
    checkbox.dataset.key = attachment.key;
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        selectedAttachmentKeys.add(attachment.key);
      } else {
        selectedAttachmentKeys.delete(attachment.key);
      }
    });

    const filename = document.createElement("span");
    filename.className = "office-hub-filename";
    filename.textContent = attachment.filename;
    filename.title = attachment.filename;

    row.append(checkbox, filename);
    list.appendChild(row);
  }

  panel.appendChild(list);

  // Send button
  const button = document.createElement("button");
  button.className = "office-hub-button";
  button.type = "button";
  button.textContent = "Send to Office Hub";
  button.addEventListener("click", async () => {
    button.disabled = true;
    setStatus(panel, "Sending…");

    const selected = attachments.filter((a) =>
      panel.querySelector(`input[data-key="${CSS.escape(a.key)}"]`)?.checked
    );

    if (selected.length === 0) {
      setStatus(panel, "No files selected.");
      button.disabled = false;
      return;
    }

    let successCount = 0;
    for (const attachment of selected) {
      try {
        setStatus(panel, `Sending ${attachment.filename}...`);
        await ingestAttachment(attachment, messageRoot);
        successCount++;
      } catch (error) {
        const msg = error instanceof Error ? error.message : "Ingest failed.";
        setStatus(panel, msg);
      }
    }

    if (successCount === selected.length) {
      setStatus(panel, `✓ ${successCount} file${successCount !== 1 ? "s" : ""} sent`);
      window.setTimeout(removePanel, 2000);
    } else if (successCount > 0) {
      setStatus(panel, `${successCount} sent, ${selected.length - successCount} failed.`);
    }

    button.disabled = false;
  });

  panel.appendChild(button);

  // Status line
  const statusEl = document.createElement("div");
  statusEl.className = "office-hub-status";
  panel.appendChild(statusEl);
}

function setStatus(panel, text) {
  if (!panel) return;
  const statusEl = panel.querySelector(".office-hub-status");
  if (statusEl) statusEl.textContent = text;
}

// ─── Ingest ───────────────────────────────────────────────────────────────────

async function autoIngest(attachments, messageRoot) {
  let sent = 0;
  let failed = 0;

  for (const attachment of attachments) {
    if (processedAttachmentKeys.has(attachment.key)) continue;
    processedAttachmentKeys.add(attachment.key);
    try {
      await ingestAttachment(attachment, messageRoot);
      sent += 1;
    } catch (error) {
      failed += 1;
      const msg = error instanceof Error ? error.message : "Office Hub ingest failed.";
      showInlineSummary(messageRoot, `Office Hub: ${msg}`);
    }
  }

  return { sent, failed };
}

async function ingestAttachment(attachment, messageRoot) {
  showInlineSummary(messageRoot, `Office Hub: sending ${attachment.filename}…`);

  const response = await sendRuntimeMessage({
    type: "INGEST_ATTACHMENT",
    url: attachment.url,
    filename: attachment.filename,
    docType: "auto",
  });

  if (response.downloaded) {
    throw new Error(response.error || "Gmail blocked extension upload.");
  }
  if (!response.ok) {
    throw new Error(response.error || `Could not send ${attachment.filename}`);
  }

  const result = response.ingest;
  const documentUrl = `${OFFICE_HUB_APP}/documents/${result.document_id}`;
  const lastIngestion = {
    documentName: response.filename || attachment.filename,
    status: result.status,
    timestamp: new Date().toISOString(),
    documentId: result.document_id,
    extractionSummary: result.extraction_summary,
    documentUrl,
  };

  await chrome.storage.local.set({ lastIngestion });
  showInlineSummary(
    messageRoot,
    `Office Hub: ${result.extraction_summary || attachment.filename}`,
    documentUrl
  );

  return result;
}

function sendRuntimeMessage(message) {
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      reject(new Error("Office Hub did not respond. Check that the backend is running."));
    }, INGEST_RESPONSE_TIMEOUT_MS);

    chrome.runtime.sendMessage(message, (response) => {
      window.clearTimeout(timeoutId);
      const err = chrome.runtime.lastError;
      if (err) { reject(new Error(err.message)); return; }
      resolve(response || { ok: false, error: "No response from background worker." });
    });
  });
}

// ─── Inline summary ───────────────────────────────────────────────────────────

function showInlineSummary(messageRoot, text, href) {
  removeSummaries();
  const summary = document.createElement("div");
  summary.className = "office-hub-summary";
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = text;
    summary.appendChild(link);
  } else {
    summary.textContent = text;
  }
  const header = document.querySelector("h2[data-thread-perm-id], h2.hP, h2") || messageRoot;
  header.insertAdjacentElement("afterend", summary);
}

function removeSummaries() {
  document.querySelectorAll(".office-hub-summary").forEach((n) => n.remove());
}

function removePanel() {
  document.querySelector(".office-hub-panel")?.remove();
}
