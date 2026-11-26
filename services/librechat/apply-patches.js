"use strict";

const fs = require("fs");

const patches = [
  {
    name: "MCP tool images reach every provider",
    path: "/app/packages/api/dist/index.cjs",
    search: "const isRecognizedProvider = RECOGNIZED_PROVIDERS.has(provider);",
    replacement: "const isRecognizedProvider = true;",
  },
  {
    name: "Every MCP tool gets an intent label",
    path: "/app/packages/api/dist/index.cjs",
    search: "if (resolved == null && !NATIVE_INTENT_TOOL_NAMES.has(def.name)) return def;",
    replacement: "if (resolved == null && !NATIVE_INTENT_TOOL_NAMES.has(def.name) && !def.name.includes(librechat_data_provider.Constants.mcp_delimiter)) return def;",
  },
];

const failedPatches = [];
for (const patch of patches) {
  const source = fs.readFileSync(patch.path, "utf8");
  const matchIndex = source.indexOf(patch.search);
  const hasSecondMatch = matchIndex !== -1 && source.includes(patch.search, matchIndex + 1);
  if (matchIndex === -1 || hasSecondMatch) {
    failedPatches.push(`${patch.name}: expected one match in ${patch.path}, found ${hasSecondMatch ? "several" : "none"}`);
    continue;
  }
  fs.writeFileSync(patch.path, `${source.slice(0, matchIndex)}${patch.replacement}${source.slice(matchIndex + patch.search.length)}`);
  console.log(`Applied patch: ${patch.name}`);
}

if (failedPatches.length > 0) {
  console.error(`LibreChat changed the patched code, update services/librechat/apply-patches.js:\n${failedPatches.join("\n")}`);
  process.exit(1);
}