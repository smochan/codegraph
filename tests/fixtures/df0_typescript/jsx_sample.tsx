// JSX fixture: function returning JSX should still capture params.
export function Greet(name: string): JSX.Element {
  return <div>{name}</div>;
}
