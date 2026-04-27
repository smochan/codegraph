import { OrderList } from "./components/OrderList";
import { UserCard } from "./components/UserCard";

export function App() {
  const userId = 1;
  return (
    <div>
      <UserCard userId={userId} />
      <OrderList userId={userId} />
    </div>
  );
}
