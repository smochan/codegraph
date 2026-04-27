import { useEffect, useState } from "react";

import { apiClient } from "../api/client";

interface Order {
  id: number;
  user_id: number;
  total_cents: number;
}

interface OrderListProps {
  userId: number;
}

export function OrderList({ userId }: OrderListProps) {
  const [orders, setOrders] = useState<Order[]>([]);

  useEffect(() => {
    apiClient.get(`/api/orders?user_id=${userId}`).then((data) => {
      setOrders(data as Order[]);
    });
  }, [userId]);

  function placeOrder(totalCents: number) {
    apiClient
      .post("/api/orders", { user_id: userId, total_cents: totalCents })
      .then((order) => {
        setOrders((prev) => [...prev, order as Order]);
      });
  }

  return (
    <div className="order-list">
      <h3>Orders</h3>
      <ul>
        {orders.map((o) => (
          <li key={o.id}>${(o.total_cents / 100).toFixed(2)}</li>
        ))}
      </ul>
      <button onClick={() => placeOrder(2500)}>Place $25 order</button>
    </div>
  );
}
