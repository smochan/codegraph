export class User {
  constructor(public name: string) {}

  greet(): string {
    return `Hi, I am ${this.name}`;
  }
}
