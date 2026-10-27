import Link from "next/link";
import { Brand } from "@/components/brand";
export default function NotFound() {
  return (
    <main className="not-found">
      <Brand />
      <h1>This route is off the map.</h1>
      <p>The page may have moved. Your saved data remains in local storage.</p>
      <Link className="button button-primary" href="/app">
        Open platform
      </Link>
    </main>
  );
}
