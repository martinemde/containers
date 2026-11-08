#!/bin/sh
set -eu
engine=${CONTAINER_ENGINE:-docker}
# Syntax/dependency/version checks only: never start listeners or device/cloud I/O.
"$engine" run --rm --network none --entrypoint node "$1" --check dist/rethink-cloud.js
"$engine" run --rm --network none --entrypoint node "$1" --input-type=module -e '
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { revision } from "./dist/util/version.js";
import { existsSync } from "node:fs";
const require = createRequire(import.meta.url);
for (const dependency of Object.keys(require("./package.json").dependencies)) require.resolve(dependency);
assert.match(revision, /^[0-9a-f]{7}$/);
assert.ok(existsSync("./dist/html"));
'
