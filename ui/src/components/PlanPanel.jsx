import React, { useState, useEffect } from 'react';

// PlanPanel fetches the current plan (todo.md) from the backend and displays it
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8009/api';

const PlanPanel = () => {
    const [content, setContent] = useState('');

    const fetchPlan = async () => {
        try {
            const res = await fetch(`${API_URL}/todo`);
            const data = await res.json();
            setContent(data.content || '');
        } catch (err) {
            console.error('Error fetching plan:', err);
        }
    };

    useEffect(() => {
        fetchPlan();
        const interval = setInterval(fetchPlan, 5000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="h-full p-4 overflow-auto bg-white">
            {content ? (
                <pre className="whitespace-pre-wrap font-mono text-sm text-gray-800">
                    {content}
                </pre>
            ) : (
                <p className="text-gray-500 italic">План пока отсутствует</p>
            )}
        </div>
    );
};

export default PlanPanel;
