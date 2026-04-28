const autoModeInput = document.getElementById("autoMode");
const lastStatus = document.getElementById("lastStatus");

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
  if (!lastIngestion) {
    lastStatus.textContent = "No documents sent yet.";
    return;
  }

  const timestamp = new Date(lastIngestion.timestamp);
  const timeText = Number.isNaN(timestamp.getTime())
    ? ""
    : ` · ${timestamp.toLocaleString()}`;
  lastStatus.textContent = `${lastIngestionName(lastIngestion)} · ${lastIngestion.status}${timeText}`;
}

function lastIngestionName(lastIngestion) {
  return lastIngestion.extractionSummary || lastIngestion.documentName || "Document";
}
