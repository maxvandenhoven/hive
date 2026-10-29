import { useEffect } from "react";
import { useLocation } from "react-router";

/** Scroll to the section named by the hash of the address, as a help link asks. */
export function useScrollToHash() {
  const { hash } = useLocation();

  useEffect(() => {
    if (hash.length > 1) {
      document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView();
    }
  }, [hash]);
}
