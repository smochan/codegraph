// React TSX fixture for DF2 — fetch inside a component function.

export function ItemList() {
  const onLoad = () => {
    fetch("/api/items");
  };
  return <button onClick={onLoad}>load</button>;
}
