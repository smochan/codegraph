// Fixture: fresh-instance binding for TS
// new UserService().getUser(id) must emit CALLS edges to BOTH
// UserService (class) and UserService.getUser (method).

export class UserService {
  getUser(id: string): string {
    return id;
  }
}

export function run(id: string): string {
  return new UserService().getUser(id);
}
