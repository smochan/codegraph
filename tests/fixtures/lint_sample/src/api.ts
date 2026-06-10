import { db, jobs } from "./schema";

// Case A — exported function with any param and any return: SHOULD fire any-on-boundary
export function processPayload(x: any): any {
  return x;
}

// Case A — exported arrow with any param: SHOULD fire any-on-boundary
export const handleInput = (data: any): string => {
  return String(data);
};

// Typed exported counterexample — SHOULD NOT fire any-on-boundary
export function typedHandler(x: string): string {
  return x.trim();
}

// Non-exported function with any — SHOULD NOT fire any-on-boundary (case A)
function internalProcess(x: any): any {
  return x;
}

// Case B — as any into db.insert().values(): SHOULD fire any-into-db-write
export async function submitJob(payload: unknown): Promise<void> {
  await db.insert(jobs).values(payload as any);
}

// Typed call — SHOULD NOT fire any-into-db-write
export async function submitTypedJob(payload: { name: string }): Promise<void> {
  await db.insert(jobs).values(payload);
}

// Keep internalProcess reachable so tree-shaking doesn't flag it
export { internalProcess };
