// Fixture for TS public-API pragma detection.

// pragma: codegraph-public-api
export function markedTsFunction(): number {
  return 1;
}

export function unmarkedTsFunction(): number {
  return 2;
}
