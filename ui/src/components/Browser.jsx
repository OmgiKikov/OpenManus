import React, { useRef, useState, useMemo } from 'react';

const extractUrlFromLogs = (logs) => {
  if (!logs || logs.length === 0) return null;

  for (let i = logs.length - 1; i >= 0; i--) {
    const log = logs[i];
    if (log.message.includes('Session debug_url:')) {
      const urlMatch = log.message.match(/: (https?:\/\/[^\s]+)/);
      if (urlMatch && urlMatch[1]) {
        return urlMatch[1];
      }
    }
  }
  return null;
};

const Browser = ({ logs }) => {
  const [url, setUrl] = useState('');
  const iframeRef = useRef(null);

  // Memoize URL extraction to prevent unnecessary processing
  const newUrl = useMemo(() => extractUrlFromLogs(logs), [logs]);

  // Only update URL state if a new URL is found and it's different from current
  if (newUrl && newUrl !== url) {
    setUrl(newUrl);
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 bg-white overflow-hidden">
        <iframe
          ref={iframeRef}
          className="w-full h-full border-none"
          sandbox="allow-same-origin allow-scripts"
          src={url}
          title="Browser preview window"
        />
      </div>
    </div>
  );
};

export default React.memo(Browser);
