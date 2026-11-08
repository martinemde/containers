import { test, expect } from "bun:test";

const workflow = Bun.YAML.parse(await Bun.file(".github/workflows/build.yml").text());
const renovate = await Bun.file("renovate.json").json();

test("base image and actions use immutable pins", async () => {
  const containerfile = await Bun.file("tailscale/Containerfile").text();
  expect(containerfile).toMatch(/^FROM docker\.io\/tailscale\/tailscale:stable@sha256:[a-f0-9]{64}\n$/);
  for (const step of workflow.jobs.build.steps.filter(step => step.uses)) {
    expect(step.uses).toMatch(/@[a-f0-9]{40}$/);
  }
});

test("PRs build without publishing; main publishes only after smoke test", () => {
  expect(workflow.on.pull_request).toBeNull();
  expect(workflow.on.push.branches).toEqual(["main"]);
  expect(workflow.on.pull_request_target).toBeUndefined();
  const steps = workflow.jobs.build.steps;
  const build = steps.find(step => step.with?.load === true);
  expect(build.with.push).toBe(false);
  expect(build.with.platforms).toBe("linux/amd64");
  const smoke = steps.findIndex(step => step.run?.includes("--entrypoint tailscale"));
  const publish = steps.findIndex(step => step.id === "publish");
  expect(smoke).toBeGreaterThan(-1);
  expect(publish).toBeGreaterThan(smoke);
  for (const step of steps.filter(step => step.id === "publish" || step.uses?.startsWith("docker/login-action"))) {
    expect(step.if).toBe("github.event_name == 'push' && github.ref == 'refs/heads/main'");
  }
});

test("Renovate discovers nested Containerfiles and keeps updates review-only", () => {
  expect(renovate.enabledManagers).toContain("renovate-config");
  const pattern = renovate.dockerfile.managerFilePatterns[0];
  expect(new RegExp(pattern.slice(1, -1)).test("tailscale/Containerfile")).toBe(true);
  expect(renovate.packageRules.at(-1)).toEqual({ matchPackageNames: ["*"], automerge: false });
});
