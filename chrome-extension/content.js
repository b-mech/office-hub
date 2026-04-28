const OFFICE_HUB_API = "http://localhost:8000";
const OFFICE_HUB_APP = "http://localhost:3000";
const PROCESSED_LABEL = "Office Hub \u2014 Processed";

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
  if (observer) {
    observer.disconnect();
  }

  observer = new MutationObserver(() => scheduleScan());
  observer.observe(document.body, {
    childList: true,
    subtree: true,
  });
}

function scheduleScan() {
  window.clearTimeout(scanTimer);
  scanTimer = window.setTimeout(scanOpenEmail, 500);
}

async function scanOpenEmail() {
  const messageRoot = findOpenMessageRoot();
  if (!messageRoot) {
    removePanel();
    return;
  }

  const messageKey = getMessageKey(messageRoot);
  if (messageKey !== currentMessageKey) {
    currentMessageKey = messageKey;
    processedAttachmentKeys = new Set();
    removePanel();
    removeSummaries();
  }

  const attachments = findPdfAttachments(messageRoot);
  if (attachments.length === 0) {
    removePanel();
    return;
  }

  const { autoMode } = await chrome.storage.sync.get({ autoMode: false });
  if (autoMode) {
    removePanel();
    await autoIngest(attachments, messageRoot);
  } else {
    renderPanel(attachments, messageRoot);
  }
}

function findOpenMessageRoot() {
  const conversation = document.querySelector('div[role="main"]');
  if (!conversation) {
    return null;
  }

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

function findPdfAttachments(messageRoot) {
  const byKey = new Map();
  const candidates = Array.from(
    messageRoot.querySelectorAll("[download_url], a[href], div[aria-label], span[aria-label]")
  );

  for (const candidate of candidates) {
    const attachment = parseAttachment(candidate);
    if (attachment && !byKey.has(attachment.key)) {
      byKey.set(attachment.key, attachment);
    }
  }

  return Array.from(byKey.values());
}

function parseAttachment(node) {
  const downloadUrl = node.getAttribute("download_url");
  if (downloadUrl) {
    const parts = downloadUrl.split(":");
    const mimeType = parts[0] || "";
    const filename = parts[1] || getFilename(node);
    const url = parts.slice(2).join(":");
    if (isPdf(filename, mimeType) && url) {
      return { node, filename, url, key: `${filename}|${url}` };
    }
  }

  const href = node.getAttribute("href");
  const filename = getFilename(node);
  if (href && isPdf(filename, "")) {
    return {
      node,
      filename,
      url: new URL(href, location.origin).toString(),
      key: `${filename}|${href}`,
    };
  }

  return null;
}

function getFilename(node) {
  const label = [
    node.getAttribute("aria-label"),
    node.getAttribute("title"),
    node.textContent,
  ]
    .filter(Boolean)
    .join(" ");
  const match = label.match(/[\w .()[\]-]+\.pdf/i);
  return match ? match[0].trim() : "attachment.pdf";
}

function isPdf(filename, mimeType) {
  return filename.toLowerCase().endsWith(".pdf") || mimeType === "application/pdf";
}

async function autoIngest(attachments, messageRoot) {
  for (const attachment of attachments) {
    if (processedAttachmentKeys.has(attachment.key)) {
      continue;
    }
    processedAttachmentKeys.add(attachment.key);
    await ingestAttachment(attachment, "auto", messageRoot);
  }
}

function renderPanel(attachments, messageRoot) {
  let panel = document.querySelector(".office-hub-panel");
  if (!panel) {
    panel = document.createElement("aside");
    panel.className = "office-hub-panel";
    document.body.appendChild(panel);
  }

  panel.innerHTML = "";

  const title = document.createElement("h2");
  title.textContent = "Office Hub PDFs";
  panel.appendChild(title);

  for (const attachment of attachments) {
    const row = document.createElement("label");
    row.className = "office-hub-attachment";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.key = attachment.key;

    const details = document.createElement("span");

    const filename = document.createElement("span");
    filename.className = "office-hub-filename";
    filename.textContent = attachment.filename;

    const select = document.createElement("select");
    select.className = "office-hub-select";
    select.dataset.key = attachment.key;
    for (const value of ["auto", "land_otp", "sale_otp"]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }

    details.append(filename, select);
    row.append(checkbox, details);
    panel.appendChild(row);
  }

  const button = document.createElement("button");
  button.className = "office-hub-button";
  button.type = "button";
  button.textContent = "Send to Office Hub";
  button.addEventListener("click", async () => {
    button.disabled = true;
    setPanelMessage(panel, "Sending...");

    try {
      const selected = attachments.filter((attachment) => {
        return panel.querySelector(`input[data-key="${cssEscape(attachment.key)}"]`)?.checked;
      });

      for (const attachment of selected) {
        const docType =
          panel.querySelector(`select[data-key="${cssEscape(attachment.key)}"]`)?.value || "auto";
        await ingestAttachment(attachment, docType, messageRoot);
      }

      setPanelMessage(panel, "Sent to Office Hub.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Office Hub ingest failed.";
      setPanelMessage(panel, message);
    } finally {
      button.disabled = false;
    }
  });
  panel.appendChild(button);
}

async function ingestAttachment(attachment, docType, messageRoot) {
  showInlineSummary(messageRoot, `Office Hub: sending ${attachment.filename}...`);
  const file = await downloadAttachment(attachment);

  const formData = new FormData();
  formData.append("file", file, attachment.filename);
  formData.append("doc_type", docType);

  const response = await fetch(`${OFFICE_HUB_API}/api/v1/ingest`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Office Hub ingest failed: ${response.status} ${errorText}`);
  }

  const result = await response.json();
  const documentUrl = `${OFFICE_HUB_APP}/documents/${result.document_id}`;
  const lastIngestion = {
    documentName: attachment.filename,
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
  applyProcessedLabel();
  return result;
}

async function downloadAttachment(attachment) {
  const response = await fetch(attachment.url, {
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`Could not download ${attachment.filename}`);
  }

  const blob = await response.blob();
  return new File([blob], attachment.filename, { type: "application/pdf" });
}

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
  document.querySelectorAll(".office-hub-summary").forEach((node) => node.remove());
}

function removePanel() {
  document.querySelector(".office-hub-panel")?.remove();
}

function setPanelMessage(panel, text) {
  let message = panel.querySelector(".office-hub-message");
  if (!message) {
    message = document.createElement("div");
    message.className = "office-hub-message";
    panel.appendChild(message);
  }
  message.textContent = text;
}

function applyProcessedLabel() {
  const labelButton =
    document.querySelector('[aria-label^="Label"], [data-tooltip^="Label"]') ||
    document.querySelector('[aria-label*="Labels"], [data-tooltip*="Labels"]');

  if (!labelButton) {
    return;
  }

  labelButton.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  labelButton.click();

  window.setTimeout(() => {
    const input =
      document.querySelector('input[aria-label*="Label"]') ||
      document.querySelector('input[placeholder*="Label"]');
    if (input) {
      input.value = PROCESSED_LABEL;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    const menuItems = Array.from(document.querySelectorAll('[role="menuitem"], [role="option"]'));
    const labelItem = menuItems.find((item) => item.textContent?.includes(PROCESSED_LABEL));
    if (labelItem) {
      labelItem.click();
      const applyButton = Array.from(document.querySelectorAll("div[role='button'], button")).find(
        (button) => /^apply$/i.test(button.textContent?.trim() || "")
      );
      applyButton?.click();
    }
  }, 250);
}

function cssEscape(value) {
  if (window.CSS?.escape) {
    return window.CSS.escape(value);
  }
  return value.replace(/["\\]/g, "\\$&");
}
