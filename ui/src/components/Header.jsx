import React from 'react';
import { CircleStackIcon, PauseIcon, ArrowDownTrayIcon } from '@heroicons/react/24/outline';

const Header = () => {
  const [isRecording, setIsRecording] = React.useState(false);
  const [isPaused, setIsPaused] = React.useState(false);

  const handleRecordToggle = () => {
    setIsRecording(!isRecording);
  };

  const handlePauseToggle = () => {
    setIsPaused(!isPaused);
  };

  const handleSave = () => {
    // Implementation for saving session
  };

  return (
    <header className="h-16 bg-white border-b border-gray-200 flex items-center px-6">
      <div className="flex items-center">
        <h1 className="text-xl font-semibold text-gray-800">OpenManus</h1>
        <span className="ml-2 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-brand-100 text-brand-800">
          智能助手
        </span>
      </div>
      <div className="ml-auto flex items-center space-x-4">
        <button
          onClick={handleRecordToggle}
          className={`p-1.5 rounded-md hover:bg-gray-100 ${
            isRecording ? 'recording' : 'text-gray-500'
          }`}
          title="记录日志"
        >
          <CircleStackIcon className="h-5 w-5" />
        </button>
        <button
          onClick={handlePauseToggle}
          className={`p-1.5 rounded-md hover:bg-gray-100 ${
            isPaused ? 'paused' : 'text-gray-500'
          }`}
          title="暂停日志"
        >
          <PauseIcon className="h-5 w-5" />
        </button>
        <button
          onClick={handleSave}
          className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100"
          title="保存会话"
        >
          <ArrowDownTrayIcon className="h-5 w-5" />
        </button>
      </div>
    </header>
  );
};

export default Header; 