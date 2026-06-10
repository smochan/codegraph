// Fixture: fresh-instance via factory function (NOT a class).
// factory().run() must NOT produce a class CALLS edge since factory
// is a function, not a class.

export function factory(): { run(): string } {
  return { run: () => "ok" };
}

export function main(): string {
  return factory().run();
}
