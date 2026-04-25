import React from 'react';
import { formatName } from './utils';

interface Props {
  firstName: string;
  lastName: string;
}

class Greeter extends React.Component<Props> {
  render() {
    const name = formatName(this.props.firstName, this.props.lastName);
    return <div>Hello, {name}!</div>;
  }
}

const App = (props: Props) => {
  const name = formatName(props.firstName, props.lastName);
  return <div>{name}</div>;
};

export default App;
export { Greeter };
