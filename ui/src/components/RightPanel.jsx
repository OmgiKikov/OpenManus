import React, { useMemo } from 'react';
import Browser from './Browser';
import { GlobeAltIcon } from '@heroicons/react/24/outline';

// Move component creation outside render function
const BrowserComponent = ({ logs }) => <Browser logs={logs} />;

const RightPanel = ({ activeTab, setActiveTab, currentTaskId, logs }) => {
  // Memoize tabs array
  const tabs = useMemo(() => [
    {
      id: 'browser',
      name: 'Браузер',
      icon: GlobeAltIcon,
      component: BrowserComponent
    }
  ], []); // Empty dependency array since tabs never change

  return (
    <div className="w-1/2 flex flex-col border-l border-gray-200">
      <div className="p-2 border-b border-gray-200 bg-white flex items-center">
        <div className="flex space-x-1">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`tab-button px-3 py-1.5 font-medium text-sm rounded-md ${activeTab === tab.id
                ? 'bg-brand-50 text-brand-700'
                : 'text-gray-600 hover:bg-gray-50'
                }`}
            >
              <tab.icon className="h-4 w-4 inline-block mr-1" />
              {tab.name}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1">
        {tabs.map(tab => (
          <div
            key={tab.id}
            className={`h-full ${activeTab === tab.id ? '' : 'hidden'}`}
          >
            <tab.component logs={logs} />
          </div>
        ))}
      </div>
    </div>
  );
};

// Wrap with React.memo to prevent re-renders if props haven't changed
export default React.memo(RightPanel, (prevProps, nextProps) => {
  // Custom comparison function to determine if re-render is needed
  return (
    prevProps.activeTab === nextProps.activeTab &&
    // Only compare logs if they would affect the visible component
    (prevProps.activeTab !== 'browser' || prevProps.logs === nextProps.logs)
  );
});
