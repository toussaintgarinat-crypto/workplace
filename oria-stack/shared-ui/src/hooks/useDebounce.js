import { useEffect, useState } from 'react';

/**
 * useDebounce — renvoie une version retardée d'une valeur (utile pour search inputs).
 *
 * Exemple :
 *   const debouncedQuery = useDebounce(query, 300);
 *   useEffect(() => { runSearch(debouncedQuery); }, [debouncedQuery]);
 */
export function useDebounce(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

export default useDebounce;
