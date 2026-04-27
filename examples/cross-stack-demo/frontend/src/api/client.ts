// Generic api-client used by all components.
//
// codegraph's DF2 detects `apiClient.get(url)` / `apiClient.post(url, body)`
// patterns and emits FETCH_CALL edges from the calling component to a
// synthetic fetch::METHOD::URL node.

export const apiClient = {
  get(url: string): Promise<unknown> {
    return fetch(url, { method: "GET" }).then((r) => r.json());
  },
  post(url: string, body: object): Promise<unknown> {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
  },
};
