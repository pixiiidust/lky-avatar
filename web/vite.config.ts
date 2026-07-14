import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

/**
 * Build identity for the session export's JSONL header (issue #40): the
 * exported eval trace must state which client build produced it. Both values
 * are resolved at BUILD time — the client never guesses at runtime — and
 * degrade to null when unknowable (e.g. building outside a git checkout).
 */

const pkg = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
) as { version?: string };

function gitShortSha(): string | null {
  try {
    return execSync("git rev-parse --short HEAD", {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return null;
  }
}

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version ?? null),
    __GIT_SHA__: JSON.stringify(gitShortSha()),
  },
});
