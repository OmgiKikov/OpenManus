'use client';

import { getTask, restartTask, terminateTask } from '@/actions/tasks';
import { ChatMessages } from '@/components/features/chat/messages';
import { ChatPreview } from '@/components/features/chat/preview';
import { Message } from '@/types/chat';
import { Tasks } from '@prisma/client';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { useCurrentMessageIndex } from '../../hooks';
import { ChatInput } from '@/components/features/chat/input';

export default function ChatPage() {
  const params = useParams();
  const router = useRouter();
  const taskId = params.taskid as string;

  const [value, setValue] = useState('');
  const [task, setTask] = useState<Tasks | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(false);
  const { currentMessageIndex, setCurrentMessageIndex } = useCurrentMessageIndex();
  const [messages, setMessages] = useState<Message[]>([]);
  const [visibleMessages, setVisibleMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [isTerminating, setIsTerminating] = useState(false);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const allMessagesRef = useRef<Message[]>([]);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const lastTaskDataRef = useRef<string>('');
  const visibleIndexRef = useRef<number>(0);

  const shouldAutoScroll = isNearBottom && currentMessageIndex === visibleMessages.length - 1;

  const handleScroll = () => {
    if (messagesContainerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = messagesContainerRef.current;
      const isNearBottom = Math.abs(scrollHeight - scrollTop - clientHeight) < 10;
      setIsNearBottom(isNearBottom);
    }
  };

  const scrollToBottom = () => {
    if (messagesContainerRef.current && shouldAutoScroll) {
      messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
    }
  };

  // 更新progressively显示的消息
  const updateVisibleMessages = () => {
    if (allMessagesRef.current.length > visibleIndexRef.current) {
      visibleIndexRef.current += 1;

      // 从头开始创建完整的可见消息列表
      const newVisibleMessages = allMessagesRef.current.slice(0, visibleIndexRef.current);
      setVisibleMessages(newVisibleMessages);

      // 如果还有更多消息，继续显示
      if (allMessagesRef.current.length > visibleIndexRef.current) {
        timerRef.current = setTimeout(updateVisibleMessages, 600);
      }
    }
  };

  const refreshTask = async () => {
    const res = await getTask({ taskId });
    if (res.error || !res.data) {
      console.error('Error fetching task:', res.error);
      return;
    }

    setTask(res.data);

    // 构建完整的消息列表
    const allMessages: Message[] = [
      { role: 'user' as const, content: { prompt: res.data.prompt } },
      ...res.data.progresses.map(step => ({ role: 'assistant' as const, type: step.type as Message['type'], content: step.content as object })),
    ];

    // 检查数据是否有变化
    const currentDataString = JSON.stringify(res.data.progresses);
    const isNewData = currentDataString !== lastTaskDataRef.current;
    lastTaskDataRef.current = currentDataString;

    // 保存所有消息到ref中
    allMessagesRef.current = allMessages;
    setMessages(allMessages);

    // 只在第一次加载或数据重置时初始化visibleMessages
    if (visibleMessages.length === 0) {
      // 停止现有的定时器
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }

      // 重置计数器
      visibleIndexRef.current = 1; // 开始只显示用户消息

      // 始终立即显示用户消息
      setVisibleMessages([allMessages[0]]);

      // 如果有助手消息，启动定时器显示
      if (allMessages.length > 1) {
        timerRef.current = setTimeout(updateVisibleMessages, 1000);
      }
    } else if (isNewData && allMessages.length > visibleIndexRef.current) {
      // 如果有新消息但不需要重置，继续显示后续消息
      if (!timerRef.current) {
        timerRef.current = setTimeout(updateVisibleMessages, 1000);
      }
    }

    if (shouldAutoScroll) {
      setCurrentMessageIndex(visibleMessages.length - 1);
      requestAnimationFrame(scrollToBottom);
    }

    setIsThinking(res.data.status !== 'completed' && res.data.status !== 'failed' && res.data.status !== 'terminated');
    setIsTerminating(res.data.status === 'terminating');
  };

  useEffect(() => {
    if (!taskId) return;
    refreshTask();

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, [taskId]);

  useEffect(() => {
    if (!taskId || !isThinking) return;
    const interval = setInterval(refreshTask, 2000);
    return () => {
      clearInterval(interval);
    };
  }, [taskId, isThinking]);

  useEffect(() => {
    if (shouldAutoScroll) {
      requestAnimationFrame(scrollToBottom);
    }
  }, [visibleMessages, shouldAutoScroll]);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const handleSubmit = async (value: { prompt: string; tools: string[]; files: File[] }) => {
    try {
      const res = await restartTask({ taskId, prompt: value.prompt, tools: value.tools, files: value.files });
      if (res.error) {
        console.error('Error restarting task:', res.error);
      }
      setIsThinking(true);
      setValue('');
      setVisibleMessages([]); // 提交新请求时重置显示消息
      visibleIndexRef.current = 0; // 重置计数器
      router.refresh();
    } catch (error) {
      console.error('Error submitting task:', error);
    }
  };

  console.log('visibleMessages', visibleMessages);
  console.log('allMessages', allMessagesRef.current);
  console.log('visibleIndex', visibleIndexRef.current);

  return (
    <div className="flex h-screen w-full flex-row justify-between">
      <div className="flex-1">
        <div className="relative flex h-screen flex-col">
          <div
            ref={messagesContainerRef}
            className="flex-3/5 space-y-4 overflow-y-auto p-4 pb-60"
            style={{
              scrollBehavior: 'smooth',
              overscrollBehavior: 'contain',
            }}
            onScroll={handleScroll}
          >
            <ChatMessages messages={visibleMessages} />
          </div>
          <ChatInput
            status={isThinking ? 'thinking' : isTerminating ? 'terminating' : 'completed'}
            onSubmit={handleSubmit}
            onTerminate={async () => {
              await terminateTask({ taskId });
              router.refresh();
            }}
          />
        </div>
      </div>
      <div className="min-w-[800px] flex-1 items-center justify-center p-2">
        <ChatPreview message={visibleMessages[currentMessageIndex]} />
      </div>
    </div>
  );
}
