/**
 * Ensures apps/web/node_modules/next exists so the repository's quality gate
 * can run, from the repo root:
 *
 *   node apps/web/node_modules/next/dist/bin/next build apps/web
 *
 * `npm install` at the root (workspaces mode) normally HOISTS next into the
 * root node_modules and leaves apps/web/node_modules empty or absent, which
 * would break the gate path. When no nested copy exists, this script links
 * the hoisted package into the workspace (a Windows junction / POSIX symlink
 * — no file copying, no version drift).
 *
 * Wired as the `postinstall` script of @veripay/web; a no-op whenever
 * apps/web/node_modules/next already resolves. It never edits package files.
 */
import { existsSync, lstatSync, mkdirSync, rmSync, symlinkSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const linkPath = join(webRoot, "node_modules", "next");

function gateBinaryResolves(base) {
  return existsSync(join(base, "dist", "bin", "next"));
}

if (gateBinaryResolves(linkPath)) {
  console.log("[ensure-next-link] apps/web/node_modules/next already resolves — nothing to do.");
  process.exit(0);
}

// Find the hoisted copy by walking up from apps/web.
let dir = webRoot;
let hoisted = null;
for (let i = 0; i < 8; i += 1) {
  dir = join(dir, "..");
  const candidate = join(dir, "node_modules", "next");
  if (gateBinaryResolves(candidate)) {
    hoisted = candidate;
    break;
  }
}

if (!hoisted) {
  console.error(
    "[ensure-next-link] no hoisted `next` package found above apps/web — run `npm install` at the repo root first."
  );
  process.exit(1);
}

mkdirSync(join(webRoot, "node_modules"), { recursive: true });
// A dangling link from a previous install would make symlinkSync throw EEXIST.
if (lstatSync(linkPath, { throwIfNoEntry: false })) {
  rmSync(linkPath, { recursive: true, force: true });
}
symlinkSync(hoisted, linkPath, process.platform === "win32" ? "junction" : "dir");

console.log(`[ensure-next-link] linked apps/web/node_modules/next -> ${hoisted}`);
