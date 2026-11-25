"use strict";

const fs = require("fs");
const yaml = require("js-yaml");

const [basePath, overridePath, outputPath] = process.argv.slice(2);

const isPlainObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

const readConfig = (path) => {
  const config = yaml.load(fs.readFileSync(path, "utf8")) ?? {};
  if (!isPlainObject(config)) {
    throw new Error(`${path} must hold a YAML mapping at the top level`);
  }
  return config;
};

const findMatchIndex = (list, overrideItem) => {
  if (isPlainObject(overrideItem) && overrideItem.name !== undefined) {
    return list.findIndex((item) => isPlainObject(item) && item.name === overrideItem.name);
  }
  return list.indexOf(overrideItem);
};

const mergeLists = (baseList, overrideList) => {
  const merged = [...baseList];
  for (const overrideItem of overrideList) {
    const matchIndex = findMatchIndex(merged, overrideItem);
    if (matchIndex === -1) {
      merged.push(overrideItem);
    } else if (isPlainObject(overrideItem)) {
      merged[matchIndex] = mergeValues(merged[matchIndex], overrideItem);
    }
  }
  return merged;
};

const mergeValues = (baseValue, overrideValue) => {
  if (isPlainObject(baseValue) && isPlainObject(overrideValue)) {
    const merged = { ...baseValue };
    for (const [key, value] of Object.entries(overrideValue)) {
      merged[key] = Object.hasOwn(merged, key) ? mergeValues(merged[key], value) : value;
    }
    return merged;
  }
  if (Array.isArray(baseValue) && Array.isArray(overrideValue)) {
    return mergeLists(baseValue, overrideValue);
  }
  return overrideValue;
};

try {
  const hasOverride = fs.existsSync(overridePath);
  const config = hasOverride ? yaml.dump(mergeValues(readConfig(basePath), readConfig(overridePath)), { lineWidth: -1, noRefs: true }) : fs.readFileSync(basePath, "utf8");
  fs.writeFileSync(outputPath, config, { mode: 0o600 });
  console.log(hasOverride ? `Merged ${overridePath} into ${basePath}` : `No ${overridePath}, using ${basePath} as is`);
} catch (error) {
  console.error(`Failed to write ${outputPath} from ${basePath} and ${overridePath}: ${error.message}`);
  process.exit(1);
}