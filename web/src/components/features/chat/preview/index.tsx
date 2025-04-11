import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getFilePath, getImageUrl } from '@/lib/image';
import { Message } from '@/types/chat';
import Markdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/default-highlight';
import { githubGist } from 'react-syntax-highlighter/dist/esm/styles/hljs';

import { useEffect, useState } from 'react';
import Image from 'next/image';

const BrowserPagePreview = ({ message }: { message: Message }) => {
  return (
    <div className="relative w-full">
      <Image
        src={getImageUrl(message.content.screenshot)}
        alt="Manus's Computer Screen"
        width={1920}
        height={1080}
        className="h-auto w-full"
        sizes="(max-width: 1920px) 100vw, 1920px"
        priority
      />
    </div>
  );
};

const NotPreview = () => {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="animate-pulse text-gray-500">Manus is not using the computer right now...</div>
    </div>
  );
};

const getFileLanguage = (path: string): string => {
  const ext = path.split('.').pop()?.toLowerCase();
  const languageMap: Record<string, string> = {
    js: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    py: 'python',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    cs: 'csharp',
    go: 'go',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    kt: 'kotlin',
    rs: 'rust',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    html: 'html',
    css: 'css',
    scss: 'scss',
    less: 'less',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    xml: 'xml',
    sql: 'sql',
    md: 'markdown',
    txt: 'text',
    log: 'text',
    ini: 'ini',
    toml: 'toml',
    conf: 'conf',
    env: 'env',
    dockerfile: 'dockerfile',
    'docker-compose': 'yaml',
  };
  return languageMap[ext || ''] || 'text';
};

const StrReplaceEditorPreview = ({ message }: { message: Message }) => {
  const [fileContent, setFileContent] = useState('');
  const [language, setLanguage] = useState('text');

  useEffect(() => {
    const path = getFilePath(message.content.args.path);
    if (!path) {
      return;
    }

    setLanguage(getFileLanguage(message.content.args.path));

    fetch(path).then(res => {
      res.text().then(data => {
        setFileContent(data);
      });
    });
  }, [message.content.args.path]);

  if (language === 'markdown') {
    return (
      <div className="markdown-body p-4">
        <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
          {fileContent}
        </Markdown>
      </div>
    );
  }

  return (
    <div className="p-4">
      <SyntaxHighlighter language={language} showLineNumbers style={githubGist} customStyle={{ fontSize: '0.875rem', lineHeight: '1.5' }}>
        {fileContent}
      </SyntaxHighlighter>
    </div>
  );
};

const PythonExecuteScriptPreview = ({ message }: { message: Message }) => {
  return (
    <SyntaxHighlighter language="python" showLineNumbers style={githubGist} customStyle={{ fontSize: '0.875rem', lineHeight: '1.5' }}>
      {message.content.args.code.trim()}
    </SyntaxHighlighter>
  );
};

const PythonExecuteResultPreview = ({ message }: { message: Message }) => {
  return (
    <SyntaxHighlighter language="json" showLineNumbers style={githubGist} customStyle={{ fontSize: '0.875rem', lineHeight: '1.5' }}>
      {message.content.result.trim()}
    </SyntaxHighlighter>
  );
};

const PreviewContent = ({ message }: { message: Message }) => {
  if (message?.type === 'agent:browser:browse:complete') {
    return <BrowserPagePreview message={message} />;
  }
  if (message?.type === 'agent:tool:execute:start' && message.content.name === 'str_replace_editor' && message.content.args.command === 'view') {
    return <StrReplaceEditorPreview message={message} />;
  }
  if (message?.type === 'agent:tool:execute:start' && message.content.name === 'str_replace_editor') {
    return <StrReplaceEditorPreview message={message} />;
  }
  if (message?.type === 'agent:tool:execute:start' && message.content.name === 'python_execute') {
    return <PythonExecuteScriptPreview message={message} />;
  }
  if (message?.type === 'agent:tool:execute:complete' && message.content.name === 'python_execute') {
    return <PythonExecuteResultPreview message={message} />;
  }

  return <NotPreview />;
};

const PreviewDescription = ({ message }: { message: Message }) => {
  if (message?.type === 'agent:browser:browse:complete') {
    return (
      <CardDescription className="text-sm">
        Manus is browsing the page{' '}
        <a href={message.content.url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">
          <code>{message.content.url}</code>
        </a>
      </CardDescription>
    );
  }
  if (message?.type === 'agent:tool:execute:start' && message.content.name === 'str_replace_editor' && message.content.args.command === 'view') {
    return (
      <CardDescription className="text-sm">
        Manus is using the computer to view the file <code>{message.content.args.path}</code>
      </CardDescription>
    );
  }
  if (message?.type === 'agent:tool:execute:start' && message.content.name === 'str_replace_editor') {
    return (
      <CardDescription className="text-sm">
        Manus is using the computer to edit the file <code>{message.content.args.path}</code>
      </CardDescription>
    );
  }
  if (message?.type === 'agent:tool:execute:start' && message.content.name === 'python_execute') {
    return <CardDescription className="text-sm">Manus is running a Python script...</CardDescription>;
  }
  if (message?.type === 'agent:tool:execute:complete' && message.content.name === 'python_execute') {
    return <CardDescription className="text-sm">Manus has finished running the Python script.</CardDescription>;
  }
  return <CardDescription className="text-sm">Manus is not using the computer right now...</CardDescription>;
};

export const ChatPreview = ({ message }: { message: Message }) => {
  return (
    <Card className="flex h-full flex-col gap-0 px-2">
      <CardHeader className="flex-none p-2 py-1">
        <CardTitle className="text-normal">Manus's Computer</CardTitle>
        <PreviewDescription message={message} />
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-2">
        <div className="h-full w-full overflow-auto rounded-md">
          <PreviewContent message={message} />
        </div>
      </CardContent>
    </Card>
  );
};
