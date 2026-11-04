import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  redirect,
  RouterProvider,
} from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiError, api, call } from "./api/client";
import { useMe } from "./api/hooks";
import { NotificationTray } from "./components/NotificationTray";
import { SearchBox } from "./components/SearchBox";
import { Avatar, Icon, ToastProvider } from "./components/ui";
import { BoardPage, type BoardSearch } from "./routes/BoardPage";
import { Home } from "./routes/Home";
import { SettingsPage } from "./routes/SettingsPage";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
    },
  },
});

function Shell() {
  const me = useMe();
  if (me.isError) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-ink-2">
        <div>
          <p className="text-[16px] font-semibold text-ink">Seltzer can’t tell who you are</p>
          <p className="mt-1 text-[13.5px]">{me.error.message}</p>
        </div>
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-4 border-b border-line bg-surface px-4 py-2">
        <Link to="/" className="flex items-center gap-2 text-[15px] font-bold tracking-tight">
          <img src="/favicon.svg" alt="" className="size-6" />
          Seltzer
        </Link>
        <SearchBox />
        <span className="flex-1" />
        <NotificationTray />
        <Link to="/settings" className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink" aria-label="Workspace settings">
          <Icon name="gear" size={18} />
        </Link>
        {me.data && <Avatar user={me.data.user} size={26} />}
      </header>
      <main className="min-h-0 flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

const rootRoute = createRootRoute({ component: Shell });

const homeRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: Home });

const VIEWS = new Set(["open", "golden", "closing_soon"]);

const boardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/boards/$boardId",
  validateSearch: (s: Record<string, unknown>): BoardSearch => ({
    card: s.card != null && Number.isFinite(Number(s.card)) ? Number(s.card) : undefined,
    view: typeof s.view === "string" && VIEWS.has(s.view) ? (s.view as BoardSearch["view"]) : undefined,
    tag: typeof s.tag === "string" ? s.tag : undefined,
    assignee: typeof s.assignee === "string" ? s.assignee : undefined,
  }),
  component: function BoardRoute() {
    const { boardId } = boardRoute.useParams();
    const search = boardRoute.useSearch();
    return <BoardPage boardId={boardId} search={search} />;
  },
});

/** /cards/42 links resolve to the card's board with the card open. */
const cardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cards/$number",
  beforeLoad: async ({ params }) => {
    const detail = await call(api.GET("/api/cards/{number}", { params: { path: { number: Number(params.number) } } }));
    throw redirect({ to: "/boards/$boardId", params: { boardId: detail.card.board_id }, search: { card: detail.card.number } });
  },
});

const settingsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/settings", component: SettingsPage });

const router = createRouter({
  routeTree: rootRoute.addChildren([homeRoute, boardRoute, cardRoute, settingsRoute]),
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
