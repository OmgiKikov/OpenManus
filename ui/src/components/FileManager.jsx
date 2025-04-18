import React, { useState, forwardRef, useImperativeHandle } from 'react';

const FileManager = forwardRef((props, ref) => {
  const [files, setFiles] = useState({});
  const [selectedFile, setSelectedFile] = useState(null);

  useImperativeHandle(ref, () => ({
    updateFiles: (file) => {
      setFiles(prevFiles => ({
        ...prevFiles,
        [file.path]: file.content
      }));
      setSelectedFile(file.path);
    },
    clear: () => {
      setFiles({});
      setSelectedFile(null);
    }
  }));

  const handleFileSelect = (path) => {
    setSelectedFile(path);
  };

  return (
    <div className="h-full flex flex-col">
      <div id="saved-files" className="p-4 border-b border-gray-200 bg-gray-50 overflow-y-auto max-h-40">
        {Object.keys(files).length === 0 ? (
          <p className="text-gray-500 italic">Еще нет сохраненных файлов</p>
        ) : (
          <div className="space-y-2">
            {Object.entries(files).map(([path, content]) => (
              <div
                key={path}
                onClick={() => handleFileSelect(path)}
                className={`p-2 rounded-md cursor-pointer ${selectedFile === path
                  ? 'bg-brand-100 text-brand-800'
                  : 'hover:bg-gray-100'
                  }`}
              >
                <div className="flex items-center">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 mr-2 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="text-sm font-medium">{path}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div id="file-preview" className="flex-1 overflow-y-auto p-4 font-mono text-sm bg-white">
        {selectedFile ? (
          <pre className="whitespace-pre-wrap">{files[selectedFile]}</pre>
        ) : (
          <div className="text-gray-500 text-center mt-4">
            Выберите файл, чтобы просмотреть содержимое
          </div>
        )}
      </div>
    </div>
  );
});

export default FileManager;
