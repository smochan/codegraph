import { db, jobs } from "./schema";

// for...of loop — should fire db-call-in-loop
export async function insertAll(items: string[]): Promise<void> {
  for (const item of items) {
    await db.insert(jobs).values(item);
  }
}

// .forEach callback — should fire db-call-in-loop
export async function updateAll(ids: number[]): Promise<void> {
  ids.forEach(async (id) => {
    await db.update(jobs).set({ processed: true }).where(id);
  });
}

// non-loop call — must NOT fire
export async function insertOne(item: string): Promise<void> {
  await db.insert(jobs).values(item);
}
