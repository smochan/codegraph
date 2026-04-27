// Fixture for DF0 TypeScript parameter / call-arg capture tests.

export function plain(a, b) {
  return a + b;
}

export function typed(a: number, b: string = "x"): boolean {
  return true;
}

export function optional(a?: number) {
  return a;
}

export function rest(...args: number[]) {
  return args.length;
}

export const arrow = (a: T) => a;

export class C {
  m(x: number): void {
    /* noop */
  }
}

export function callers() {
  plain(1, "x", y);
  fetch("/x", { method: "POST", body: data });
  multiObj({ a: 1 }, { b: 2 });
  trailingObj(1, { x: 2 });
  complex(a + b, foo.bar());
  member(obj.x.y);
  spread(...args);
}
