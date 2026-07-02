const { test } = require("node:test");
const assert = require("node:assert");

const { greet } = require("./hello");

test("greet default", () => {
  assert.strictEqual(greet(), "Hello, world!");
});

test("greet name", () => {
  assert.strictEqual(greet("ai-orch"), "Hello, ai-orch!");
});
