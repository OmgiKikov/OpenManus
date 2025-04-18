import React, { useState, useRef, useEffect } from 'react';
import { PaperAirplaneIcon } from '@heroicons/react/24/outline';

// Get API URL from environment variable or fallback to localhost
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8009/api';

const ChatArea = ({
  currentTaskId,
  setCurrentTaskId,
  logs,
  isLoading,
  onStartLoading,
  onStopLoading
}) => {
  const [messages, setMessages] = useState([{
    content: 'Привет! Я интеллектуальный помощник OpenAgent. Введите ваш вопрос или команду, и я постараюсь помочь.',
    sender: 'bot',
    timestamp: new Date().toISOString(),
    isStepMessage: true
  }]);
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Process logs for messages
  useEffect(() => {
    if (!logs || logs.length === 0) return;

    let currentStepMessages = [];
    let currentStep = null;

    const shouldShowLog = (message) => {
      return !message.startsWith('开始处理任务') && !message.startsWith('Token usage:') && !message.startsWith('Session debug_url:');
    };

    logs.forEach(log => {
      if (!shouldShowLog(log.message)) {
        return;
      }

      // Check if this is a step execution message
      const isStepMessage = log.message.startsWith('Executing step');

      if (isStepMessage) {
        // If we have a previous step, add all its messages
        if (currentStep && currentStepMessages.length > 0) {
          currentStepMessages.forEach(msg => {
            setMessages(prev => [
              ...prev,
              {
                content: msg,
                sender: 'bot',
                timestamp: new Date().toISOString()
              }
            ]);
          });
        }
        // Add the step message with the thinking icon
        setMessages(prev => [
          ...prev,
          {
            content: log.message,
            sender: 'bot',
            timestamp: new Date().toISOString(),
            step: currentStep,
            isStepMessage: true
          }
        ]);
        // Start a new step
        currentStep = log.message;
        currentStepMessages = [];
      } else if (currentStep) {
        // Add message to current step without thinking icon
        currentStepMessages.push(log.message);
        setMessages(prev => [
          ...prev,
          {
            content: log.message,
            sender: 'bot',
            timestamp: new Date().toISOString(),
            step: currentStep
          }
        ]);
      } else {
        // Handle logs that come before any step
        setMessages(prev => [
          ...prev,
          {
            content: log.message,
            sender: 'bot',
            timestamp: new Date().toISOString()
          }
        ]);
      }
    });
  }, [logs]);

  // Status polling
  useEffect(() => {
    if (!currentTaskId || !isLoading) return;

    const pollStatus = setInterval(async () => {
      try {
        const response = await fetch(`${API_URL}/status/${currentTaskId}`);
        const data = await response.json();

        if (data.status === 'completed') {
          onStopLoading();
          if (data.response) {
            setMessages(prev => [
              ...prev,
              {
                content: data.response,
                sender: 'bot',
                timestamp: new Date().toISOString()
              }
            ]);
          }
          setCurrentTaskId(null);
        }
      } catch (error) {
        console.warn('Error polling status:', error);
      }
    }, 1000);

    return () => clearInterval(pollStatus);
  }, [currentTaskId, isLoading, setCurrentTaskId, onStopLoading]);

  const formatMessage = (message) => {
    let formattedMessage = message.replace(/```(\w*)\n([\s\S]*?)```/g, (match, language, code) => {
      return `<pre class="bg-gray-800 text-gray-200 rounded p-3 my-2 overflow-x-auto code-block"><code class="language-${language}">${escapeHtml(code.trim())}</code></pre>`;
    });

    formattedMessage = formattedMessage.replace(/`([^`]+)`/g, '<code class="bg-gray-100 text-gray-800 px-1 rounded">$1</code>');
    formattedMessage = formattedMessage.replace(/\n/g, '<br>');

    return formattedMessage;
  };

  const escapeHtml = (text) => {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const newMessage = {
      content: inputValue,
      sender: 'user',
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, newMessage, {
      content: 'Думаю...',
      sender: 'bot',
      timestamp: new Date().toISOString(),
      isStepMessage: true
    }]);
    setInputValue('');
    onStartLoading();

    try {
      const response = await fetch(`${API_URL}/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: inputValue })
      });

      const data = await response.json();
      setCurrentTaskId(data.task_id);
    } catch (error) {
      console.error('Error sending message:', error);
      setMessages(prev => {
        const filteredMessages = prev.filter(msg => msg.sender !== 'bot');
        return [...filteredMessages, {
          content: 'Ошибка при отправке запроса, попробуйте снова.',
          sender: 'bot',
          timestamp: new Date().toISOString()
        }];
      });
      onStopLoading();
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-white scrollbar-thin">
        {messages.map((message, index) => (
          <div
            key={index}
            className={`flex items-start ${message.sender === 'bot' ? 'bot-message' : 'user-message'}`}
          >
            <div className="flex-shrink-0 mr-3">
              <div className={`h-8 w-8 rounded-full flex items-center justify-center ${message.sender === 'bot' && message.isStepMessage
                ? 'bg-brand-100 text-brand-600'
                : message.sender === 'user' ? 'bg-gray-100 text-gray-600' : ''
                }`}>
                {
                  message.sender === 'user' && (
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                    </svg>
                  )
                }
                {message.sender === 'bot' && message.isStepMessage && (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                )}
              </div>
            </div>
            <div className={`flex-1 ${message.sender === 'bot' ? 'bg-gray-50' : 'bg-brand-50'
              } rounded-lg p-4`}>
              <div
                className={`${message.sender === 'bot' ? 'text-gray-800' : 'text-gray-800'}`}
                dangerouslySetInnerHTML={{ __html: formatMessage(message.content) }}
              />
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 border-t border-gray-200 bg-white">
        <div className="flex">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Введите ваш вопрос или команду..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-l-lg focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
          />
          <button
            onClick={handleSendMessage}
            disabled={isLoading || !inputValue.trim()}
            className={`bg-brand-500 hover:bg-brand-600 text-white px-4 py-2 rounded-r-lg transition-colors duration-200 flex items-center ${isLoading || !inputValue.trim() ? 'opacity-50 cursor-not-allowed' : ''
              }`}
          >
            <PaperAirplaneIcon className="h-5 w-5 mr-1" />
            Отправить
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatArea;
