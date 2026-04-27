# cross-stack-demo

A tiny but realistic project that exercises every codegraph capability
end-to-end: a React frontend with `fetch` and an `apiClient` that calls a
FastAPI backend with SQLAlchemy repositories.

## What this demo shows

Run codegraph against this fixture and you'll see the full data flow from a
React `UserCard`'s fetch all the way to the SQL `User` model — with role
classification (HANDLER/SERVICE/COMPONENT/REPO), DF0 argument capture at every
call site, and DF3/DF4 cross-layer stitching.

## Setup

No install needed for the demo — codegraph just statically analyses the source.

```bash
# From the repo root
cd /path/to/codegraph
codegraph build --no-incremental --root examples/cross-stack-demo
codegraph analyze
codegraph dataflow trace "GET /api/users/{user_id}"
```

## Expected output

```
Flow trace from: GET /api/users/{user_id}  (confidence: 0.90)

  [backend] backend/api/routes/users.py:18  backend.api.routes.users.get_user  HANDLER
              GET /api/users/{user_id}
   ↓
  [backend] backend/api/routes/users.py:14  backend.api.routes.users._get_service
   ↓
  [backend] backend/services/user_service.py:9  backend.services.user_service.UserService.get_user  SERVICE
              args: (user_id)
   ↓
  [backend] backend/repositories/user_repository.py:11  backend.repositories.user_repository.UserRepository.get_by_id  REPO
              args: (user_id)
   ↓
  [db]      backend/models.py  backend.models.User  REPO
              args: (op=READS_FROM)
```

## What to look for

- **HANDLER / SERVICE / REPO role tags** in the right column
- **DF0 args + kwargs** at each hop showing `(user_id)` flowing through
- **Cross-layer transitions:**
  - frontend → backend via `match_route()` matching `fetch("/api/users/${id}")` to `@router.get("/api/users/{user_id}")`
  - backend → db via SQLAlchemy `session.query(User)` emitting READS_FROM

## Files

```
examples/cross-stack-demo/
├── backend/
│   ├── api/main.py                     # FastAPI app
│   ├── api/routes/users.py             # GET /api/users/{user_id}, POST /api/users
│   ├── api/routes/orders.py            # GET /api/orders, POST /api/orders
│   ├── services/user_service.py        # UserService — calls UserRepository
│   ├── services/order_service.py       # OrderService — calls OrderRepository
│   ├── repositories/user_repository.py # UserRepository — session.query(User)
│   ├── repositories/order_repository.py
│   └── models.py                       # SQLAlchemy User, Order
└── frontend/
    └── src/
        ├── App.tsx
        ├── components/
        │   ├── UserCard.tsx            # fetch("/api/users/${id}", ...)
        │   └── OrderList.tsx           # apiClient.get / apiClient.post
        └── api/client.ts               # apiClient.get/post helpers
```
