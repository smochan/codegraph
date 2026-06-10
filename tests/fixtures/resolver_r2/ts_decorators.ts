// Fixture: TS decorator CALLS edges.
// @Injectable() on class and @Get(':id') on method must each emit
// CALLS edges with decorator:true metadata.

export function Injectable(): ClassDecorator {
  return (target) => target;
}

export function Get(path: string): MethodDecorator {
  return (_target, _key, _desc) => _desc;
}

@Injectable()
export class UserController {
  @Get(":id")
  getUser(id: string): string {
    return id;
  }
}
