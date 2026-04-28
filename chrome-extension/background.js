chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get({ autoMode: false }, ({ autoMode }) => {
    chrome.storage.sync.set({ autoMode: Boolean(autoMode) });
  });
});
