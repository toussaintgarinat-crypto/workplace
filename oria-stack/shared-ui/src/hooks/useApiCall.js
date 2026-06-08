import { useCallback, useState } from 'react';

/**
 * useApiCall — wrappe une fn async + expose loading/error/data.
 *
 * Exemple :
 *   const { call, loading, error, data } = useApiCall(api.fetchUser);
 *   <button onClick={() => call(userId)} disabled={loading}>Load</button>
 */
export function useApiCall(fn) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);

  const call = useCallback(async (...args) => {
    setLoading(true);
    setError(null);
    try {
      const result = await fn(...args);
      setData(result);
      return result;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [fn]);

  const reset = useCallback(() => {
    setLoading(false);
    setError(null);
    setData(null);
  }, []);

  return { call, loading, error, data, reset };
}

export default useApiCall;
