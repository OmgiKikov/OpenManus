import React, { useState, useEffect, useRef } from 'react';

const Logger = ({ currentTaskId }) => {
  const [filter, setFilter] = useState('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [logs, setLogs] = useState([]);
  const [lastIndex, setLastIndex] = useState(0);
  const [isRecording, setIsRecording] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const outputRef = useRef(null);

  useEffect(() => {
    // Set up log polling
    const pollLogs = async () => {
      if (isPaused || !currentTaskId) return;
      
      try {
        const response = await fetch(`http://localhost:8009/api/logs/${currentTaskId}?last_index=${lastIndex}`);
        const data = await response.json();
        
        if (data.logs && data.logs.length > 0) {
          setLogs(prevLogs => [...prevLogs, ...data.logs]);
          setLastIndex(data.next_index);
          
          if (autoScroll && outputRef.current) {
            setTimeout(() => {
              outputRef.current.scrollTop = outputRef.current.scrollHeight;
            }, 0);
          }
        }
      } catch (error) {
        console.warn('Error polling logs:', error);
      }
    };

    const pollInterval = setInterval(pollLogs, 1000);
    return () => clearInterval(pollInterval);
  }, [lastIndex, isPaused, autoScroll, currentTaskId]);

  const handleClearLogs = () => {
    setLogs([]);
    setLastIndex(0);
  };

  const toggleAutoScroll = () => {
    setAutoScroll(!autoScroll);
  };

  const toggleRecording = () => {
    setIsRecording(!isRecording);
  };

  const togglePause = () => {
    setIsPaused(!isPaused);
  };

  const getLogClassName = (log) => {
    let className = 'mb-1 leading-relaxed ';
    
    if (log.message.includes('thoughts') || log.message.includes('思考')) {
      return className + 'text-blue-400 italic';
    }
    
    if (log.message.includes('执行工具') || log.message.includes('Activating tool')) {
      return className + 'text-purple-500 font-semibold';
    }
    
    switch(log.level) {
      case 'ERROR':
        return className + 'text-red-500';
      case 'WARNING':
        return className + 'text-yellow-500';
      case 'INFO':
        return className + 'text-green-400';
      default:
        return className + 'text-gray-300';
    }
  };

  const shouldShowLog = (log) => {
    if (filter === 'all') return true;
    
    const message = log.message;
    
    switch (filter) {
      case 'info':
        return log.level === 'INFO' || (!message.includes('ERROR') && !message.includes('WARNING') && !message.includes('执行工具'));
      case 'warning':
        return log.level === 'WARNING' || message.includes('WARNING');
      case 'error':
        return log.level === 'ERROR' || message.includes('ERROR');
      case 'tool':
        return message.includes('执行工具') || message.includes('Activating tool');
      default:
        return true;
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="bg-gray-800 border-b border-gray-700 p-2 flex items-center">
        <div className="flex items-center space-x-2">
          <button 
            onClick={handleClearLogs}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 text-white text-xs rounded-md"
          >
            清空日志
          </button>
          <button 
            onClick={toggleAutoScroll}
            className={`px-3 py-1 ${autoScroll ? 'bg-blue-600 hover:bg-blue-700' : 'bg-gray-700 hover:bg-gray-600'} text-white text-xs rounded-md`}
          >
            自动滚动: {autoScroll ? '开' : '关'}
          </button>
          <button
            onClick={toggleRecording}
            className={`px-3 py-1 ${isRecording ? 'text-red-500' : 'text-gray-400'} hover:bg-gray-600 text-xs rounded-md`}
          >
            记录
          </button>
          <button
            onClick={togglePause}
            className={`px-3 py-1 ${isPaused ? 'text-yellow-500' : 'text-gray-400'} hover:bg-gray-600 text-xs rounded-md`}
          >
            暂停
          </button>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-gray-700 text-white text-xs rounded-md px-2 py-1 border border-gray-600"
          >
            <option value="all">所有日志</option>
            <option value="info">信息</option>
            <option value="warning">警告</option>
            <option value="error">错误</option>
            <option value="tool">工具执行</option>
          </select>
        </div>
      </div>
      <div 
        ref={outputRef}
        className="flex-1 overflow-y-auto p-4 bg-gray-900 text-gray-200 font-mono text-sm scrollbar-thin"
        style={{ height: 'calc(100% - 40px)' }}
        onScroll={(e) => {
          const element = e.target;
          const isNearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 50;
          if (autoScroll !== isNearBottom) {
            setAutoScroll(isNearBottom);
          }
        }}
      >
        {logs.filter(shouldShowLog).map((log, index) => (
          <div key={index} className={getLogClassName(log)}>
            {log.message}
          </div>
        ))}
      </div>
    </div>
  );
};

export default Logger; 