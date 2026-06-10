import { db, jobs } from "./schema";

export async function allJobs() {
  return await db.select().from(jobs);
}

export async function activeJobs() {
  return await db.select().from(jobs).where("status = 'active'");
}

export async function recentJobs() {
  return await db.select().from(jobs).limit(10);
}

export function notAQuery(): string {
  return ["a", "b"].join(",");
}
