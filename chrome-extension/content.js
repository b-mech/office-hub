// content.js
const OFFICE_HUB_API = "http://localhost:8000";
const OFFICE_HUB_APP = "http://localhost:3000";

let observer = null;
let scanTimer = null;
let currentMessageKey = "";
let processedAttachmentKeys = new Set();

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
    removePanel();
    removeSummaries();
  }

  const attachments = findPdfAttachments(messageRoot);
  if (attachments.length === 0) { removePanel(); return; }

  const { autoMode } = await chrome.storage.sync.get({ autoMode: false });
  if (autoMode) {
    removePanel();
    await autoIngest(attachments, messageRoot);
  } else {
    renderPanel(attachments, messageRoot);
  }
}

// ─── Gmail DOM helpers ────────────────────────────────────────────────────────

function findOpenMessageRoot() {
  const conversation = document.querySelector('div[role="main"]');
  if (!conversation) return null;
  const expandedMessages = Array.from(
    conversation.querySelectorAll('div[role="listitem"], .adn, .gs')
  ).filter((node) => node.querySelector("[download_url], a[href]"));
  return expandedMessages.at(-1) || conversation;
}

function getMessageKey(messageRoot) {
  const subject = document.querySelector("h2[data-thread-perm-id], h2.hP, h2")?.textContent || "";
  const date = messageRoot.querySelector("[title][alt], [title]")?.getAttribute("title") || "";
  return `${location.href}|${subject.trim()}|${date}`;
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
  return (filename || "")
    .replace(/^(download|open|preview|attachment)\s+/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

// ─── Panel UI ─────────────────────────────────────────────────────────────────

function renderPanel(attachments, messageRoot) {
  removePanel();

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
    checkbox.checked = true;
    checkbox.dataset.key = attachment.key;

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
  const statusEl = panel.querySelector(".office-hub-status");
  if (statusEl) statusEl.textContent = text;
}

// ─── Ingest ───────────────────────────────────────────────────────────────────

async function autoIngest(attachments, messageRoot) {
  for (const attachment of attachments) {
    if (processedAttachmentKeys.has(attachment.key)) continue;
    processedAttachmentKeys.add(attachment.key);
    try {
      await ingestAttachment(attachment, messageRoot);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Office Hub ingest failed.";
      showInlineSummary(messageRoot, `Office Hub: ${msg}`);
    }
  }
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
    chrome.runtime.sendMessage(message, (response) => {
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
