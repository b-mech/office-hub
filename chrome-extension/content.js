// content.js
const OFFICE_HUB_API = "http://localhost:8000";
const OFFICE_HUB_APP = "http://localhost:3000";
const INGEST_RESPONSE_TIMEOUT_MS = 620000;
const OFFICE_HUB_ICON_URL = chrome.runtime.getURL("favicon.png");
const KRISTY_EMAIL = "";

let observer = null;
let scanTimer = null;
let currentMessageKey = "";
let processedAttachmentKeys = new Set();
let selectedAttachmentKeys = new Set();
let renderedAttachmentSignature = "";
let panelExpanded = false;
let renderedChangeOrderBannerKey = "";
let dismissedChangeOrderBannerKeys = new Set();

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
  if (!messageRoot) {
    selectedAttachmentKeys = new Set();
    renderedAttachmentSignature = "";
    renderedChangeOrderBannerKey = "";
    dismissedChangeOrderBannerKeys = new Set();
    panelExpanded = false;
    removeChangeOrderBanners();
    renderPanel([], null);
    return;
  }

  const messageKey = getMessageKey(messageRoot);
  if (messageKey !== currentMessageKey) {
    currentMessageKey = messageKey;
    processedAttachmentKeys = new Set();
    selectedAttachmentKeys = new Set();
    renderedAttachmentSignature = "";
    renderedChangeOrderBannerKey = "";
    panelExpanded = false;
    removeSummaries();
    removeChangeOrderBanners();
  }

  renderChangeOrderBannerIfNeeded(messageRoot, messageKey);

  const attachments = findPdfAttachments(messageRoot);
  if (attachments.length === 0) {
    selectedAttachmentKeys = new Set();
    renderedAttachmentSignature = "";
    panelExpanded = false;
    renderPanel([], messageRoot);
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
  if (messagesWithPdfAttachments.length > 0) {
    return messagesWithPdfAttachments.at(-1);
  }
  const messagesWithBodies = expandedMessages.filter((node) => node.querySelector(".a3s"));
  return messagesWithBodies.at(-1) || conversation;
}

function getMessageKey(messageRoot) {
  const subject = document.querySelector("h2[data-thread-perm-id], h2.hP, h2")?.textContent || "";
  const date = messageRoot.querySelector("[title][alt], [title]")?.getAttribute("title") || "";
  const sender = getSenderEmail(messageRoot);
  return `${location.href}|${subject.trim()}|${sender}|${date}`;
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
  const roots = getAttachmentSearchRoots(messageRoot);

  const nodes = roots.flatMap((root) => Array.from(root.querySelectorAll("[download_url]")));
  for (const node of nodes) {
    const raw = node.getAttribute("download_url") || "";
    // Gmail format: "application/pdf:filename.pdf:https://..."
    if (!raw.toLowerCase().startsWith("application/pdf:")) continue;

    const parsed = parseGmailDownloadUrl(raw);
    if (!parsed) continue;

    const { filename, url } = parsed;

    if (!byUrl.has(url)) {
      byUrl.set(url, { filename, url, key: url });
    }
  }

  // Fallback: href-based links for attachments without download_url
  if (byUrl.size === 0) {
    const links = roots.flatMap((root) => Array.from(root.querySelectorAll("a[href]")));
    for (const link of links) {
      const href = link.getAttribute("href") || "";
      const filename = extractFilenameFromLink(link);
      if (!looksLikeAttachmentLink(href) && !isPdfFilename(filename)) continue;

      if (!isPdfFilename(filename)) continue;

      const url = new URL(href, location.origin).toString();
      if (!byUrl.has(url)) {
        byUrl.set(url, { filename, url, key: url });
      }
    }
  }

  return Array.from(byUrl.values());
}

function getAttachmentSearchRoots(messageRoot) {
  const roots = [messageRoot];
  const main = document.querySelector('div[role="main"]');
  if (main && main !== messageRoot) {
    roots.push(main);
  }
  return roots.filter(Boolean);
}

function parseGmailDownloadUrl(raw) {
  const match = raw.match(/^application\/pdf:([^:]*):(.*)$/i);
  if (!match) return null;

  const filename = cleanFilename(match[1]) || "attachment.pdf";
  const url = match[2];
  if (!url) return null;
  return { filename, url };
}

function looksLikeAttachmentLink(href) {
  return (
    href.includes("disp=attd") ||
    href.includes("disp=safe") ||
    href.includes("view=att") ||
    href.includes("attid=") ||
    href.includes("th=")
  );
}

function extractFilenameFromLink(link) {
  // Try aria-label or data-tooltip first — these are clean
  for (const attr of ["aria-label", "data-tooltip", "title", "download"]) {
    const val = link.getAttribute(attr) || "";
    const match = val.match(/([^/\\]+\.pdf)/i);
    if (match) return cleanFilename(match[1]);
  }

  const nearbyText = [
    link.textContent || "",
    link.closest("[role='listitem'], .aQH, .aZo, .aQy, .brc, .adn, .gs")?.textContent || "",
  ].join(" ");
  const match = nearbyText.match(/([^/\\\n\r\t]+\.pdf)/i);
  if (match) return cleanFilename(match[1]);

  return "";
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

// ─── Change order email detection ─────────────────────────────────────────────

function renderChangeOrderBannerIfNeeded(messageRoot, messageKey) {
  const match = getChangeOrderMatch(messageRoot);
  if (!match) {
    removeChangeOrderBanners();
    renderedChangeOrderBannerKey = "";
    return;
  }

  if (dismissedChangeOrderBannerKeys.has(messageKey)) {
    return;
  }

  if (renderedChangeOrderBannerKey === messageKey && document.querySelector(".office-hub-co-banner")) {
    return;
  }

  removeChangeOrderBanners();
  renderedChangeOrderBannerKey = messageKey;

  const banner = document.createElement("div");
  banner.className = "office-hub-co-banner";
  banner.dataset.officeHubMessageKey = messageKey;

  const text = document.createElement("span");
  text.className = "office-hub-co-banner-text";
  text.textContent = "Change Order detected — extract details into Office Hub?";

  const actions = document.createElement("div");
  actions.className = "office-hub-co-banner-actions";

  const extractButton = document.createElement("button");
  extractButton.type = "button";
  extractButton.className = "office-hub-co-button office-hub-co-button--primary";
  extractButton.textContent = "Extract";
  extractButton.addEventListener("click", async () => {
    extractButton.disabled = true;
    extractButton.textContent = "Extracting...";
    try {
      const response = await sendRuntimeMessage({
        type: "EXTRACT_CHANGE_ORDER",
        emailBody: match.emailBody,
      });
      if (!response.ok) {
        throw new Error(response.error || "Change order extraction failed.");
      }
      banner.remove();
      renderedChangeOrderBannerKey = "";
    } catch (error) {
      extractButton.disabled = false;
      extractButton.textContent = "Extract";
      text.textContent = error instanceof Error ? error.message : "Change order extraction failed.";
    }
  });

  const dismissButton = document.createElement("button");
  dismissButton.type = "button";
  dismissButton.className = "office-hub-co-button office-hub-co-button--ghost";
  dismissButton.textContent = "Dismiss";
  dismissButton.addEventListener("click", () => {
    dismissedChangeOrderBannerKeys.add(messageKey);
    banner.remove();
    renderedChangeOrderBannerKey = messageKey;
  });

  actions.append(extractButton, dismissButton);
  banner.append(text, actions);

  const bodyNode = findMessageBodyNode(messageRoot);
  if (bodyNode) {
    bodyNode.insertAdjacentElement("beforebegin", banner);
  } else {
    messageRoot.prepend(banner);
  }
}

function getChangeOrderMatch(messageRoot) {
  if (!KRISTY_EMAIL.trim()) return null;

  const senderEmail = getSenderEmail(messageRoot).toLowerCase();
  if (senderEmail !== KRISTY_EMAIL.trim().toLowerCase()) return null;

  const subject = getEmailSubject();
  const emailBody = getEmailBody(messageRoot);
  if (!/change order/i.test(`${subject}\n${emailBody}`)) return null;

  return { emailBody };
}

function getSenderEmail(messageRoot) {
  const emailNode =
    messageRoot.querySelector("[email]") ||
    messageRoot.querySelector("[data-hovercard-id*='@']") ||
    document.querySelector("[email], [data-hovercard-id*='@']");

  const rawEmail =
    emailNode?.getAttribute("email") ||
    emailNode?.getAttribute("data-hovercard-id") ||
    emailNode?.getAttribute("title") ||
    emailNode?.textContent ||
    "";

  const match = rawEmail.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
  return match ? match[0] : "";
}

function getEmailSubject() {
  return document.querySelector("h2[data-thread-perm-id], h2.hP, h2")?.textContent?.trim() || "";
}

function getEmailBody(messageRoot) {
  const bodyNode = findMessageBodyNode(messageRoot);
  return normalizeEmailText(bodyNode?.innerText || messageRoot.innerText || "");
}

function findMessageBodyNode(messageRoot) {
  return (
    messageRoot.querySelector(".a3s.aiL") ||
    messageRoot.querySelector(".a3s") ||
    messageRoot.querySelector("[role='textbox']") ||
    null
  );
}

function normalizeEmailText(text) {
  return text.replace(/\u00a0/g, " ").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

function removeChangeOrderBanners() {
  document.querySelectorAll(".office-hub-co-banner").forEach((node) => node.remove());
}

// ─── Panel UI ─────────────────────────────────────────────────────────────────

function renderPanel(attachments, messageRoot) {
  const attachmentSignature = attachments.map((attachment) => attachment.key).join("|");
  const existingPanel = document.querySelector(".office-hub-panel");
  const existingMode = existingPanel?.dataset.mode || "";
  const nextMode = panelExpanded && attachments.length > 0 ? "expanded" : "launcher";
  if (
    existingPanel &&
    attachmentSignature === renderedAttachmentSignature &&
    existingMode === nextMode
  ) {
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
  panel.className = `office-hub-panel office-hub-panel--${nextMode}`;
  panel.dataset.mode = nextMode;
  document.body.appendChild(panel);

  if (nextMode === "launcher") {
    const launcher = document.createElement("button");
    launcher.className = "office-hub-launcher";
    launcher.type = "button";
    launcher.title = attachments.length > 0
      ? `${attachments.length} PDF${attachments.length !== 1 ? "s" : ""} detected`
      : "Office Hub";
    launcher.setAttribute("aria-label", launcher.title);

    const icon = document.createElement("img");
    icon.className = "office-hub-launcher-icon";
    icon.src = OFFICE_HUB_ICON_URL;
    icon.alt = "";
    icon.draggable = false;
    launcher.appendChild(icon);

    if (attachments.length > 0) {
      const documentBadge = document.createElement("span");
      documentBadge.className = "office-hub-document-badge";
      documentBadge.setAttribute("aria-hidden", "true");
      launcher.appendChild(documentBadge);
    }

    launcher.addEventListener("click", () => {
      if (attachments.length === 0) return;
      panelExpanded = true;
      renderPanel(attachments, messageRoot);
    });

    panel.appendChild(launcher);
    return;
  }

  // Header
  const header = document.createElement("div");
  header.className = "office-hub-panel-header";
  const title = document.createElement("span");
  title.className = "office-hub-panel-title";
  const titleIcon = document.createElement("img");
  titleIcon.className = "office-hub-panel-title-icon";
  titleIcon.src = OFFICE_HUB_ICON_URL;
  titleIcon.alt = "";
  titleIcon.draggable = false;
  const titleText = document.createElement("span");
  titleText.textContent = "Office Hub";
  title.append(titleIcon, titleText);
  const closeBtn = document.createElement("button");
  closeBtn.className = "office-hub-panel-close";
  closeBtn.textContent = "×";
  closeBtn.addEventListener("click", () => {
    panelExpanded = false;
    renderPanel(attachments, messageRoot);
  });
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
      window.setTimeout(() => {
        panelExpanded = false;
        renderPanel(attachments, messageRoot);
      }, 2000);
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
