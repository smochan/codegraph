import React from 'react';
import App from './Component';

describe('App', () => {
  it('renders without crashing', () => {
    const result = render(<App firstName="John" lastName="Doe" />);
    expect(result).toBeDefined();
  });
});
