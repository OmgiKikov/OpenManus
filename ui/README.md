# OpenManus UI

A modern React-based user interface for OpenManus intelligent assistant, featuring a chat interface, browser preview, logging system, and file management capabilities.

## Features

- 💬 Real-time chat interface with bot/user messages
- 🌐 Embedded browser with zoom controls
- 📝 Advanced logging system with filtering and auto-scroll
- 📁 File management system
- 🎨 Modern, responsive design using Tailwind CSS
- ⌨️ Keyboard shortcuts support
- 🔄 Session management
- 🎯 Component-based architecture

## Tech Stack

- React 18
- Tailwind CSS
- Heroicons
- Modern JavaScript (ES6+)

## Project Structure

```
ui/
├── public/
│   └── index.html
├── src/
│   ├── components/
│   │   ├── App.jsx           # Main application component
│   │   ├── Browser.jsx       # Browser preview component
│   │   ├── ChatArea.jsx      # Chat interface component
│   │   ├── FileManager.jsx   # File management component
│   │   ├── Footer.jsx        # Footer component
│   │   ├── Header.jsx        # Header with controls
│   │   ├── Logger.jsx        # Logging system component
│   │   ├── MainContent.jsx   # Main content layout
│   │   ├── RightPanel.jsx    # Right panel with tabs
│   │   └── Sidebar.jsx       # Sidebar with history
│   ├── hooks/
│   │   └── useApi.js         # Custom API hooks
│   ├── styles/
│   │   └── globals.css       # Global styles
│   └── index.js              # Application entry point
├── package.json
└── tailwind.config.js
```

## Getting Started

### Prerequisites

- Node.js 14.0 or later
- npm 6.0 or later

### Installation

1. Clone the repository:
\`\`\`bash
git clone <repository-url>
cd ui
\`\`\`

2. Install dependencies:
\`\`\`bash
npm install
\`\`\`

3. Start the development server:
\`\`\`bash
npm start
\`\`\`

The application will be available at `http://localhost:3000`.

## Available Scripts

- `npm start` - Runs the app in development mode
- `npm test` - Launches the test runner
- `npm run build` - Builds the app for production
- `npm run eject` - Ejects from Create React App

## Key Features

### Chat Interface
- Real-time message exchange
- Automatic scrolling
- Loading indicators
- Message history

### Browser Component
- URL display and management
- Zoom controls (0.5x to 2.0x)
- Sandboxed iframe for security
- External link opening

### Logging System
- Multiple log levels (info, warning, error, tool)
- Auto-scroll functionality
- Log filtering
- Clear logs option

### File Management
- File listing and preview
- Syntax highlighting
- File selection and viewing

## Keyboard Shortcuts

- `Alt + 1` - Switch to Browser tab
- `Alt + 2` - Switch to Logs tab
- `Alt + 3` - Switch to Files tab
- `Ctrl + R` - Toggle recording
- `Ctrl + P` - Toggle log pause
- `Ctrl + S` - Save session
- `Ctrl + N` - New chat

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with [Create React App](https://create-react-app.dev/)
- Styled with [Tailwind CSS](https://tailwindcss.com/)
- Icons from [Heroicons](https://heroicons.com/)
- Inspired by @mannaandpoem project 

## Technical Implementation

### Browser Component Implementation

The browser component uses a sandboxed iframe with custom zoom controls and URL management:

```jsx
// Browser.jsx - Key Implementation
const Browser = () => {
  const [url, setUrl] = useState('');
  const [zoomLevel, setZoomLevel] = useState(0.8);
  const iframeRef = useRef(null);

  // Zoom implementation using CSS transforms
  useEffect(() => {
    const applyZoom = () => {
      const iframeDoc = iframeRef.current?.contentDocument;
      if (iframeDoc?.body) {
        iframeDoc.body.style.zoom = zoomLevel;
        iframeDoc.body.style.transformOrigin = 'top left';
        iframeDoc.body.style.transform = `scale(${zoomLevel})`;
        iframeDoc.body.style.width = `${100/zoomLevel}%`;
      }
    };
    applyZoom();
  }, [zoomLevel]);

  return (
    <iframe
      ref={iframeRef}
      className="w-full h-full border-none"
      sandbox="allow-same-origin allow-scripts"
    />
  );
};
```

### API Integration and Polling

Custom hook for API polling with automatic cleanup:

```jsx
// useApi.js - Polling Implementation
export const usePolling = (url, interval = 1000) => {
  const [data, setData] = useState(null);
  const [isPolling, setIsPolling] = useState(true);

  useEffect(() => {
    let timeoutId;
    const fetchData = async () => {
      try {
        const response = await fetch(url);
        const json = await response.json();
        setData(json);
        if (isPolling) {
          timeoutId = setTimeout(fetchData, interval);
        }
      } catch (err) {
        console.error(err);
      }
    };

    fetchData();
    return () => {
      clearTimeout(timeoutId);
      setIsPolling(false);
    };
  }, [url, interval, isPolling]);

  return { data, isPolling, setIsPolling };
};
```

### Chat System Implementation

Real-time chat with message handling and auto-scrolling:

```jsx
// ChatArea.jsx - Message Handling
const ChatArea = ({ currentTaskId, setCurrentTaskId }) => {
  const [messages, setMessages] = useState([]);
  const messagesEndRef = useRef(null);

  // Auto-scroll implementation
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Message sending implementation
  const handleSendMessage = async () => {
    try {
      const response = await fetch('/api/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: inputValue })
      });
      const data = await response.json();
      setCurrentTaskId(data.task_id);
    } catch (error) {
      console.error('Error:', error);
    }
  };
};
```

### Logging System

Advanced logging with filtering and real-time updates:

```jsx
// Logger.jsx - Log Management
const Logger = () => {
  const [filter, setFilter] = useState('all');
  const [autoScroll, setAutoScroll] = useState(true);
  const [logs, setLogs] = useState([]);

  // Log filtering implementation
  const filteredLogs = logs.filter(log => {
    if (filter === 'all') return true;
    return log.type === filter;
  });

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center space-x-2">
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="bg-gray-700 text-white text-xs rounded-md"
        >
          <option value="all">所有日志</option>
          <option value="info">信息</option>
          <option value="warning">警告</option>
          <option value="error">错误</option>
          <option value="tool">工具执行</option>
        </select>
      </div>
      <div className="flex-1 overflow-y-auto">
        {filteredLogs.map((log, index) => (
          <div key={index} className={`log-entry log-${log.type}`}>
            {log.message}
          </div>
        ))}
      </div>
    </div>
  );
};
```

### File Management System

File system with preview and selection capabilities:

```jsx
// FileManager.jsx - File Handling
const FileManager = () => {
  const [files, setFiles] = useState({});
  const [selectedFile, setSelectedFile] = useState(null);

  // File preview implementation
  const renderFilePreview = () => {
    if (!selectedFile) return null;
    const content = files[selectedFile];
    return (
      <pre className="whitespace-pre-wrap">
        {content}
      </pre>
    );
  };

  return (
    <div className="h-full flex flex-col">
      <div className="overflow-y-auto max-h-40">
        {Object.entries(files).map(([path, content]) => (
          <div
            key={path}
            onClick={() => setSelectedFile(path)}
            className={selectedFile === path ? 'bg-brand-100' : ''}
          >
            {path}
          </div>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto">
        {renderFilePreview()}
      </div>
    </div>
  );
};
```

### State Management

The application uses React's built-in state management with hooks:

```jsx
// App.jsx - Global State Management
const App = () => {
  const [currentTaskId, setCurrentTaskId] = useState(null);
  return (
    <div className="flex h-screen">
      <Sidebar />
      <MainContent
        currentTaskId={currentTaskId}
        setCurrentTaskId={setCurrentTaskId}
      />
    </div>
  );
};
```

## API Endpoints

The UI interacts with the following endpoints:

- `POST /api/send` - Send chat messages
- `GET /api/logs/:taskId` - Retrieve logs for a task
- `GET /api/status/:taskId` - Get task status
- `GET /api/files/:path` - Get file contents

## Browser Security

The browser component implements several security measures:

1. Sandboxed iframe with limited permissions:
```html
<iframe sandbox="allow-same-origin allow-scripts" />
```

2. URL validation before loading
3. External link handling with user confirmation
4. Content isolation through iframe boundaries

## Performance Optimizations

1. Debounced log updates
2. Virtualized list rendering for logs
3. Lazy loading of components
4. Optimized re-renders using React.memo
5. Efficient state updates using functional updates 