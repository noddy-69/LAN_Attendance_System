"use client";

import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,       // 15 s — data considered fresh
      gcTime: 5 * 60_000,      // 5 min — keep unused cache
      retry: 1,
      // Near-real-time updates without a manual refresh: refetch when the user returns
      // to the tab/app, and poll every 20 s while the tab is focused. So an approval in
      // the admin/HR/manager portal shows up in the employee portal on its own. Individual
      // queries can override refetchInterval (e.g. notifications poll on their own cadence).
      refetchOnWindowFocus: true,
      refetchInterval: 20_000,
      refetchIntervalInBackground: false,  // don't poll while the tab is hidden (saves battery)
    },
    mutations: {
      retry: 0,
    },
  },
});
