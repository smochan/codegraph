import { useEffect, useState } from "react";

interface User {
  id: number;
  email: string;
  name: string;
}

interface UserCardProps {
  userId: number;
}

export function UserCard({ userId }: UserCardProps) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    fetch(`/api/users/${userId}`, { method: "GET" })
      .then((r) => r.json())
      .then((data) => setUser(data));
  }, [userId]);

  if (!user) return <div>Loading…</div>;
  return (
    <div className="user-card">
      <h3>{user.name}</h3>
      <p>{user.email}</p>
    </div>
  );
}
