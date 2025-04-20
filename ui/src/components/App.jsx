import React, { useState } from 'react';
import Sidebar from './Sidebar';
import MainContent from './MainContent';
import '../styles/globals.css';

const App = () => {
  const [currentTaskId, setCurrentTaskId] = useState(null);

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <MainContent currentTaskId={currentTaskId} setCurrentTaskId={setCurrentTaskId} />
    </div>
  );
};

export default App;
