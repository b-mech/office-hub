// popup.js
const autoModeInput = document.getElementById("autoMode");
const lastIngestionSection = document.getElementById("lastIngestionSection");
const lastStatus = document.getElementById("lastStatus");
const reviewLink = document.getElementById("reviewLink");

init();

async function init() {
  const { autoMode } = await chrome.storage.sync.get({ autoMode: false });
  autoModeInput.checked = Boolean(autoMode);

  const { lastIngestion } = await chrome.storage.local.get({ lastIngestion: null });
  renderLastIngestion(lastIngestion);

  autoModeInput.addEventListener("change", async () => {
    await chrome.storage.sync.set({ autoMode: autoModeInput.checked });
  });
}

function renderLastIngestion(lastIngestion) {
  if (!lastIngestion) return;

  const name = lastIngestion.extractionSummary || lastIngestion.documentName || "Document";
  const timestamp = new Date(lastIngestion.timestamp);
  const timeText = !Number.isNaN(timestamp.getTime())
    ? timestamp.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "";

  lastStatus.textContent = `${name}${timeText ? " · " + timeText : ""}`;
  if (lastIngestion.documentUrl) {
    reviewLink.href = lastIngestion.documentUrl;
  }
  lastIngestionSection.classList.remove("hidden");
}
