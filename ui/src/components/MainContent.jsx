import React, { useState } from 'react';
import Header from './Header';
import ChatArea from './ChatArea';
import RightPanel from './RightPanel';
import Footer from './Footer';
import useLogPolling from '../hooks/useLogPolling';

const MainContent = ({ currentTaskId, setCurrentTaskId }) => {
  const [activeTab, setActiveTab] = useState('browser');
  const [isLoading, setIsLoading] = useState(false);
  const { logs, resetLogs } = useLogPolling(currentTaskId, isLoading);

  const handleStartLoading = () => {
    setIsLoading(true);
    resetLogs();
  };

  const handleStopLoading = () => {
    setIsLoading(false);
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <ChatArea
          currentTaskId={currentTaskId}
          setCurrentTaskId={setCurrentTaskId}
          logs={logs}
          isLoading={isLoading}
          onStartLoading={handleStartLoading}
          onStopLoading={handleStopLoading}
        />
        <RightPanel
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          currentTaskId={currentTaskId}
          logs={logs}
        />
      </div>
      <Footer />
    </div>
  );
};

export default MainContent;
