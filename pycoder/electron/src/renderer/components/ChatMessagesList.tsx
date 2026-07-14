/**
 * ChatMessagesList — AI 对话消息列表子组件
 */
import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage } from '../types';

interface Props {
    messages: ChatMessage[];
    isStreaming: boolean;
    reasoningText: string;
}

export const ChatMessagesList: React.FC<Props> = ({ messages, isStreaming, reasoningText }) => {
    const endRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    if (messages.length === 0 && !isStreaming) {
        return (
            <div className="chat-empty">
                <div className="chat-empty-icon">{'\u{1F916}'}</div>
                <p>{'开始与 AI 助手对话'}</p>
                <p className="chat-empty-hint">
                    {'输入 /help 查看命令，使用 @ 引用文件或代码'}
                </p>
            </div>
        );
    }

    return (
        <div className="chat-messages">
            {messages.map((msg) => (
                <div key={msg.id} className={`chat-message ${msg.role}`}>
                    <div className="message-avatar">
                        {msg.role === 'user' ? '\u{1F464}' : '\u{1F916}'}
                    </div>
                    <div className="message-content">
                        <div className="message-role">
                            {msg.role === 'user' ? '你' : 'AI'}
                        </div>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {msg.content}
                        </ReactMarkdown>
                    </div>
                </div>
            ))}
            {isStreaming && (
                <div className="chat-message assistant streaming">
                    <div className="message-avatar">{'\u{1F916}'}</div>
                    <div className="message-content">
                        {reasoningText && (
                            <details className="reasoning-details" open>
                                <summary>{'推理过程'}</summary>
                                <pre className="reasoning-text">{reasoningText}</pre>
                            </details>
                        )}
                        <span className="typing-indicator">
                            <span className="typing-dot" />
                            <span className="typing-dot" />
                            <span className="typing-dot" />
                        </span>
                    </div>
                </div>
            )}
            <div ref={endRef} />
        </div>
    );
};
