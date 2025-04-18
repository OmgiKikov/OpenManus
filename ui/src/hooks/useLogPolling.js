import { useState, useEffect } from 'react';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8009/api';

const useLogPolling = (taskId, isLoading = true) => {
  const [lastIndex, setLastIndex] = useState(0);
  const [logs, setLogs] = useState([]);

  useEffect(() => {
    if (!taskId || !isLoading) return;

    const pollLogs = async () => {
      try {
        const response = await fetch(`${API_URL}/logs/${taskId}?last_index=${lastIndex}`);
        const data = await response.json();

        if (data.logs && data.logs.length > 0) {
          setLogs(prevLogs => [...prevLogs, ...data.logs]);
          setLastIndex(data.next_index);
        }
      } catch (error) {
        console.warn('Error polling logs:', error);
      }
    };

    const pollInterval = setInterval(pollLogs, 1000);

    return () => clearInterval(pollInterval);
  }, [taskId, lastIndex, isLoading]);

  const resetLogs = () => {
    setLogs([]);
    setLastIndex(0);
  };

  return {
    logs,
    lastIndex,
    resetLogs
  };
};

export default useLogPolling;
