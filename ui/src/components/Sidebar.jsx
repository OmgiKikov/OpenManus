import React from 'react';
import { PlusIcon, TrashIcon } from '@heroicons/react/24/outline';

const Sidebar = () => {
  const handleNewChat = () => {
    // Implementation for new chat
  };

  const handleClearHistory = () => {
    // Implementation for clearing history
  };

  return (
    <div className="w-64 bg-white border-r border-gray-200 flex flex-col">
      <header className="h-16 border-b border-gray-200 flex items-center px-4">
        <div className="flex items-center">
          <div className="text-brand-500">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          </div>
          <h1 className="text-xl font-semibold text-brand-600 ml-2">OpenAgent</h1>
        </div>
      </header>

      <div className="p-4 border-b border-gray-200">
        <button
          onClick={handleNewChat}
          className="w-full bg-brand-500 hover:bg-brand-600 text-white py-2 px-4 rounded-md transition-colors duration-200 flex items-center justify-center"
        >
          <PlusIcon className="h-5 w-5 mr-1" />
          Новая задача
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        <h2 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2 px-2">
          История
        </h2>
        <div id="history-list" className="space-y-1">
          {/* History items will be rendered here */}
        </div>
      </div>

      <div className="p-4 border-t border-gray-200">
        <button
          onClick={handleClearHistory}
          className="w-full bg-gray-200 hover:bg-gray-300 text-gray-700 py-2 px-4 rounded-md transition-colors duration-200 flex items-center justify-center"
        >
          <TrashIcon className="h-5 w-5 mr-1" />
          Очистить историю
        </button>
      </div>
    </div>
  );
};

export default Sidebar;
