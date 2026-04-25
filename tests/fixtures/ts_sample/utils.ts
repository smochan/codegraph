/**
 * Utility functions.
 */
export function add(a: number, b: number): number {
  return a + b;
}

export function formatName(first: string, last: string): string {
  const result = `${first} ${last}`;
  return result.trim();
}

export const multiply = (a: number, b: number): number => {
  return a * b;
};
