// Fixture for loop_depth / in_loop metadata tests.

export function withLoops(items: string[]): void {
  for (const item of items) {
    doWork(item);
  }

  items.forEach((x) => {
    doWork(x);
  });
}

export function withoutLoop(): void {
  doWork("direct");
}

export function chainedBeforeMap(): void {
  getUsers().map((u) => doWork(u));
}
