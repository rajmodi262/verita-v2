import { Link } from "react-router-dom";

import { EmptyState } from "../../components/ui";

export default function NotFoundPage() {
  return (
    <main id="main">
      <EmptyState title="No such page" action={<Link to="/">Back to the start</Link>}>
        <p>The address may be mistyped, or the page may have moved.</p>
      </EmptyState>
    </main>
  );
}
