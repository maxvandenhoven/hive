import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

/**
 * Create the query client; every failed mutation is reported in a toast.
 *
 * Failed queries are reported too if their `meta` sets `toastErrors`, for queries that
 * follow a click rather than render a page, which shows its own errors.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.toastErrors === true) {
          toast.error(error.message);
        }
      },
    }),
    mutationCache: new MutationCache({
      onError: (error) => {
        toast.error(error.message);
      },
    }),
    defaultOptions: { queries: { retry: 1, staleTime: 5_000 } },
  });
}
