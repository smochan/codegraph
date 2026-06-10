import { startServer } from "./server";

test("server boots", () => {
  console.log("debug output is fine in tests");
  startServer(8080);
});
