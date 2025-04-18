import { useState, useEffect } from 'react';

export const usePolling = (url, interval = 1000) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [isPolling, setIsPolling] = useState(true);

  useEffect(() => {
    let timeoutId;

    const fetchData = async () => {
      try {
        const response = await fetch(url);
        const json = await response.json();
        setData(json);
      } catch (err) {
        setError(err);
      }

      if (isPolling) {
        timeoutId = setTimeout(fetchData, interval);
      }
    };

    fetchData();

    return () => {
      clearTimeout(timeoutId);
      setIsPolling(false);
    };
  }, [url, interval, isPolling]);

  return { data, error, isPolling, setIsPolling };
}; 