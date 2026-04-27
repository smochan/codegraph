// Fixture for DF2 FETCH_CALL extraction tests.

export function getItems() {
  fetch("/api/items");
}

export function postItem(name: string, email: string) {
  fetch("/api/items", {
    method: "POST",
    body: JSON.stringify({ name, email }),
  });
}

export function postRaw() {
  fetch("/api/raw", { method: "POST", body: "raw-string" });
}

export function axiosGet() {
  axios.get("/api/items");
}

export function axiosPostBody() {
  axios.post("/api/items", { name: "x" });
}

export function axiosConfigCall() {
  axios({ method: "PUT", url: "/api/x", data: { foo: 1, bar: 2 } });
}

export function swrFetch() {
  useSWR("/api/items", (u: string) => fetch(u));
}

export function deleteItem() {
  apiClient.delete("/api/items/1");
}

export function templateUrl(id: string) {
  fetch(`/api/items/${id}`);
}

export function dynamicUrl(url: string) {
  fetch(url);
}

export function multiCalls() {
  fetch("/api/a");
  fetch("/api/b");
  axios.get("/api/c");
}

// Top-level fetch — should be silently skipped (no enclosing FUNCTION/METHOD).
fetch("/api/top-level-skip");
