import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";

const staticDirectory = join(process.cwd(), ".next", "static");
const loopbackApiPattern = /https?:\/\/(?:127\.0\.0\.1|localhost):8000/g;

async function findLoopbackUrls(directory) {
  const matches = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      matches.push(...(await findLoopbackUrls(path)));
    } else if (entry.name.endsWith(".js")) {
      const content = await readFile(path, "utf8");
      if (loopbackApiPattern.test(content)) {
        matches.push(path);
      }
      loopbackApiPattern.lastIndex = 0;
    }
  }
  return matches;
}

const matches = await findLoopbackUrls(staticDirectory);
if (matches.length > 0) {
  console.error("Client bundle contains a loopback backend URL:");
  for (const match of matches) {
    console.error(`- ${match}`);
  }
  process.exit(1);
}

console.log("Client API URL check passed.");
