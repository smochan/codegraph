import { User } from "./models";

export function createUser(name: string): User {
  return new User(name);
}
