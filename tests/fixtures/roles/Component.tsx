import React from "react";

export function UserCard(props: { name: string }) {
  return <div>{props.name}</div>;
}

export class LegacyCard extends React.Component {
  render() {
    return <div>legacy</div>;
  }
}
