#!/bin/sh
set -eu
engine=${CONTAINER_ENGINE:-docker}
# Syntax/dependency/version checks only: never start listeners or device/cloud I/O.
"$engine" run --rm --network none --entrypoint node "$1" --check dist/rethink-cloud.js
"$engine" run --rm --network none -e EXPECTED_REVISION="${2:-e96ae725850019c59547c360ec757957b9fa9ddb}" --entrypoint node "$1" --input-type=module -e '
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { revision } from "./dist/util/version.js";
import { existsSync } from "node:fs";
const require = createRequire(import.meta.url);
for (const dependency of Object.keys(require("./package.json").dependencies)) require.resolve(dependency);
assert.equal(revision, process.env.EXPECTED_REVISION.slice(0, 7));
assert.ok(existsSync("./dist/html"));
'
