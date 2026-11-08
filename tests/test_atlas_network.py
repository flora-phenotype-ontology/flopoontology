"""Regressions for interrupted requests poisoning the browser's shared data cache."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_browser_recovers_from_transient_requests_and_failed_cached_loads():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser helper tests")
    root = Path(__file__).resolve().parents[1]
    script = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({
  URL, URLSearchParams, TypeError, Error, Promise,
  document: {baseURI: "http://atlas.test/", getElementById: () => null},
  window: {addEventListener: () => {}},
  setTimeout: (fn) => fn(),
});
const source = fs.readFileSync("web/saudi/app.js", "utf8");
vm.runInContext(source.replace(/route\(\);\s*$/, ""), context);
(async () => {
  let calls = 0;
  context.fetch = async () => {
    if (++calls === 1) throw new TypeError("NetworkError when attempting to fetch resource.");
    return {ok: true, json: async () => ({recovered: true})};
  };
  assert.equal((await vm.runInContext('requestJson("/sparql")', context)).recovered, true);
  assert.equal(calls, 2);

  calls = 0;
  context.fetch = async () => ({ok: true, json: async () => {
    if (++calls === 1) throw new TypeError("Connection interrupted while reading body");
    return {recovered: true};
  }});
  assert.equal((await vm.runInContext('requestJson("/summary.json")', context)).recovered, true);
  assert.equal(calls, 2);

  calls = 0;
  context.fetch = async () => {
    calls++;
    return {ok: false, status: 400, text: async () => "Invalid query"};
  };
  await assert.rejects(vm.runInContext('requestJson("/sparql")', context), /Invalid query/);
  assert.equal(calls, 1); // deterministic query errors must not be retried

  calls = 0;
  context.fetch = async () => {
    if (++calls <= 2) throw new TypeError("NetworkError");
    return {ok: true, json: async () => ({recovered: true})};
  };
  const load = () => vm.runInContext('cached("shared", () => requestJson("/summary.json"))', context);
  const failed = await Promise.allSettled([load(), load()]);
  assert.ok(failed.every(result => result.status === "rejected"));
  assert.equal(calls, 2); // concurrent consumers share the same request/retry
  assert.equal((await load()).recovered, true); // navigation/Retry can recover without a reload
  assert.equal(calls, 3);
  await load();
  assert.equal(calls, 3); // successful results remain cached
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", script], cwd=root, check=True, capture_output=True, text=True)
