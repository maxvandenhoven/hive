import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

/** Create the query client; every failed mutation is reported in a toast. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    mutationCache: new MutationCache({
      onError: (error) => {
        toast.error(error.message);
      },
    }),
    defaultOptions: { queries: { retry: 1, staleTime: 5_000 } },
  });
}
